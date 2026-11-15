"""Subscription billing: invoices, renewals, grace period, read-only lock and payments.

Lifecycle of a paid plan
  trial/active ── invoice issued `invoice_days_before` days before the period (or trial) ends
             └─ period ends unpaid → past_due (full access, warning banner)
                   └─ `grace_days` later still unpaid → expired: the workspace becomes read-only
                      (everyone can still read and export; administrators can still pay)
  paying the invoice → active, period extended (a long-expired workspace restarts from today)
  cancel at period end → cancelled when the period ends (read-only)

Free plans are never invoiced. A subscription with no period end and no trial end is on a manual
arrangement with HOLIDO and is skipped by the automatic run.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from flask import current_app, g
from sqlalchemy import select

from app import audit
from app.extensions import db
from app.models import Membership, Organization, Subscription
from app.models.billing import BillingSettings, Invoice, Payment
from app.notify import notify
from app.rbac import permissions_for_role

CENT = Decimal("0.01")
MONTHS = {"monthly": 1, "annual": 12}


def add_months(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    import calendar
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def as_date(dt):
    if dt is None:
        return None
    return dt.date() if isinstance(dt, datetime) else dt


def to_dt(d):
    return datetime.combine(d, time(0, 0), tzinfo=timezone.utc)


def price(plan, cycle):
    return Decimal(plan.annual_price if cycle == "annual" else plan.monthly_price or 0)


def period_end(sub):
    """When the current trial or paid period ends (a date), or None for manual arrangements."""
    if sub.status == Subscription.TRIAL and sub.trial_ends_at:
        return as_date(sub.trial_ends_at)
    return as_date(sub.current_period_end)


def billing_admins(org):
    """Members who manage billing (organization administrators and anyone granted billing.manage)."""
    out = set()
    for m in db.session.execute(select(Membership).where(Membership.organization_id == org.id,
                                                         Membership.status == Membership.ACTIVE)).scalars():
        if m.role and (m.role.is_admin or "billing.manage" in permissions_for_role(m.role)):
            out.add(m.user_id)
    return out


def _next_number(today):
    stmt = select(BillingSettings).where(BillingSettings.id == 1)
    if db.engine.dialect.name == "postgresql":
        stmt = stmt.with_for_update()
    s = db.session.execute(stmt).scalar_one_or_none() or BillingSettings.get(create=True)
    n = s.next_invoice_number
    s.next_invoice_number = n + 1
    db.session.flush()
    return f"ZTV-{today.year}-{n:05d}"


def issue_invoice(sub, start, plan=None, cycle=None, today=None, due_on=None, note=None):
    """Invoice one period of a plan. Prices and tax are copied, so later price changes do not alter it."""
    today = today or date.today()
    plan = plan or sub.plan
    cycle = cycle or sub.billing_cycle
    s = BillingSettings.get()
    org = sub.organization
    end = add_months(start, MONTHS.get(cycle, 1))
    subtotal = price(plan, cycle).quantize(CENT)
    rate = Decimal(s.tax_rate or 0) if s.tax_label else Decimal(0)
    tax = (subtotal * rate / 100).quantize(CENT, ROUND_HALF_UP)
    desc = (f"ZENTAVA {plan.name} plan, {'yearly' if cycle == 'annual' else 'monthly'} subscription: "
            f"{start:%d %b %Y} to {end - timedelta(days=1):%d %b %Y}")
    inv = Invoice(organization_id=org.id, number=_next_number(today), subscription_id=sub.id, plan_id=plan.id,
                  billing_cycle=cycle, period_start=start, period_end=end, issued_on=today,
                  due_on=due_on or max(start, today + timedelta(days=3)), currency=plan.currency,
                  lines=[{"description": desc, "amount": str(subtotal)}] + ([{"description": note, "amount": "0.00"}]
                                                                            if note else []),
                  subtotal=subtotal, tax_label=s.tax_label or None, tax_rate=rate, tax_amount=tax,
                  total=subtotal + tax, status="open",
                  bill_to={"name": org.name, "address": org.address, "email": org.email,
                           "registration_number": org.registration_number, "country": org.country},
                  issuer={"name": s.company_name, "address": s.company_address, "tax_id": s.company_tax_id,
                          "email": s.company_email})
    db.session.add(inv)
    db.session.flush()
    audit.record("billing.invoice_issued", f"Invoice {inv.number} issued ({inv.currency} {inv.total})",
                 entity=inv, organization_id=org.id)
    notify(billing_admins(org), "billing", f"Invoice {inv.number}: {inv.currency} {inv.total:,.2f} due "
           f"{inv.due_on:%d %b %Y}", "Pay it from the Billing page to keep full access.", "billing.index",
           organization_id=org.id, exclude_current=False, dedupe_key=f"inv-issued-{inv.id}", org_slug=org.slug)
    return inv


def open_invoice(org):
    return Invoice.query.filter(Invoice.organization_id == org.id, Invoice.status == "open") \
        .order_by(Invoice.due_on).first()


def state(org):
    """What billing means for this organization right now (for banners and the read-only lock)."""
    sub = org.subscription
    today = date.today()
    st = {"sub": sub, "locked": False, "level": None, "message": None, "invoice": None}
    if sub is None:
        return st
    inv = open_invoice(org)
    st["invoice"] = inv
    pe = period_end(sub)
    grace = BillingSettings.get().grace_days
    if sub.status == Subscription.EXPIRED:
        st.update(locked=True, level="danger",
                  message="The subscription has lapsed, so the workspace is read-only. "
                          "An administrator can pay the open invoice on the Billing page to restore full access.")
    elif sub.status == Subscription.CANCELLED:
        st.update(locked=True, level="danger",
                  message="The subscription was cancelled, so the workspace is read-only. Contact HOLIDO to restart it.")
    elif sub.status == Subscription.PAST_DUE:
        lock_on = (as_date(sub.current_period_end) or today) + timedelta(days=grace)
        st.update(level="warning",
                  message=f"Payment is overdue. The workspace becomes read-only on {lock_on:%d %b %Y} unless the "
                          "invoice is paid.")
    elif inv is not None and inv.due_on <= today + timedelta(days=7):
        st.update(level="info", message=f"Invoice {inv.number} ({inv.currency} {inv.total:,.2f}) is due on "
                                        f"{inv.due_on:%d %b %Y}.")
    elif sub.status == Subscription.TRIAL and pe and pe <= today + timedelta(days=7):
        st.update(level="info", message=f"The free trial ends on {pe:%d %b %Y}.")
    if sub.cancel_at_period_end and not st["locked"] and pe:
        st.update(level=st["level"] or "info",
                  message=(st["message"] + " " if st["message"] else "") +
                  f"The subscription is set to end on {pe:%d %b %Y}.")
    return st


def record_payment(inv, method, amount, reference, received_on=None, recorded_by=None, note=None,
                   channel=None, provider_status=None, started_by=None):
    """Record a successful payment once (references are unique) and apply it."""
    existing = Payment.query.filter_by(reference=reference).first()
    if existing is not None:
        if existing.status != "succeeded":
            existing.status, existing.provider_status = "succeeded", provider_status or existing.provider_status
            existing.received_on = received_on or date.today()
            existing.channel = channel or existing.channel
            existing.amount = Decimal(amount).quantize(CENT)
            db.session.flush()
            audit.record("billing.payment", f"{inv.number}: {existing.currency} {existing.amount} received "
                         f"({Payment.METHODS[existing.method]})", entity=inv, organization_id=inv.organization_id)
            apply_payment(inv)
        return existing
    p = Payment(organization_id=inv.organization_id, invoice_id=inv.id, method=method, reference=reference,
                amount=Decimal(amount).quantize(CENT), currency=inv.currency, status="succeeded",
                received_on=received_on or date.today(), note=note, channel=channel, provider_status=provider_status,
                recorded_by_id=recorded_by.id if recorded_by else None,
                started_by_id=started_by.id if started_by else None)
    db.session.add(p)
    db.session.flush()
    audit.record("billing.payment", f"{inv.number}: {p.currency} {p.amount} received ({Payment.METHODS[method]})",
                 entity=inv, organization_id=inv.organization_id)
    apply_payment(inv)
    return p


def apply_payment(inv):
    """Once an invoice is fully paid, extend the subscription to cover its period."""
    db.session.refresh(inv)
    if inv.status != "open" or inv.balance > 0:
        return False
    today = date.today()
    inv.status, inv.paid_on = "paid", today
    sub = db.session.get(Subscription, inv.subscription_id) if inv.subscription_id else None
    if sub is not None:
        new_end = inv.period_end
        if new_end <= today and sub.status == Subscription.EXPIRED:   # restoring a locked workspace: a full period from today
            new_end = add_months(today, MONTHS.get(inv.billing_cycle, 1))
            audit.record("billing.restarted", f"Paid after the period had ended; new period runs to {new_end}",
                         entity=sub, organization_id=sub.organization_id)
        current = period_end(sub)
        if current is None or new_end > current:
            sub.current_period_end = to_dt(new_end)
        if inv.plan_id and inv.plan_id != sub.plan_id:
            sub.plan_id = inv.plan_id
        sub.billing_cycle = inv.billing_cycle
        if sub.pending_plan_id == inv.plan_id:
            sub.pending_plan_id, sub.pending_cycle = None, None
        sub.status = Subscription.ACTIVE
        sub.past_due_since = None
    notify(billing_admins(inv.organization), "billing", f"Payment received: invoice {inv.number} is paid",
           "Thank you.", "billing.index", organization_id=inv.organization_id, exclude_current=False,
           dedupe_key=f"inv-paid-{inv.id}", org_slug=inv.organization.slug)
    return True


def run(today=None):
    """Daily (safe to run hourly): issue invoices, move to past due / read-only, send reminders."""
    from app.tenancy import clear_tenant, set_tenant
    today = today or date.today()
    s = BillingSettings.get()
    totals = {"invoices": 0, "past_due": 0, "expired": 0, "cancelled": 0, "reminders": 0, "free_renewed": 0}
    orgs = Organization.query.filter_by(status=Organization.ACTIVE).all()
    for org in orgs:
        sub = org.subscription
        if sub is None or sub.status in (Subscription.EXPIRED, Subscription.CANCELLED):
            continue
        set_tenant(org.id)
        g.tenant = org
        try:
            pe = period_end(sub)
            if pe is None:
                continue
            if sub.cancel_at_period_end and today >= pe:
                sub.status = Subscription.CANCELLED
                audit.record("billing.cancelled", "Subscription ended (cancelled at period end)", entity=sub,
                             organization_id=org.id)
                notify(billing_admins(org), "billing", "Your ZENTAVA subscription has ended",
                       "The workspace is now read-only.", "billing.index", organization_id=org.id,
                       exclude_current=False, dedupe_key=f"sub-cancel-{sub.id}-{pe}", org_slug=org.slug)
                totals["cancelled"] += 1
                db.session.commit()
                continue
            plan = sub.pending_plan or sub.plan
            cycle = sub.pending_cycle or sub.billing_cycle
            if price(plan, cycle) <= 0:
                if today >= pe:   # free plans simply roll on
                    sub.status = Subscription.ACTIVE
                    sub.current_period_end = to_dt(add_months(pe, MONTHS.get(cycle, 1)))
                    if sub.pending_plan_id:
                        sub.plan_id, sub.billing_cycle = sub.pending_plan_id, cycle
                        sub.pending_plan_id, sub.pending_cycle = None, None
                    totals["free_renewed"] += 1
                db.session.commit()
                continue
            inv = Invoice.query.filter(Invoice.subscription_id == sub.id, Invoice.period_start == pe,
                                       Invoice.status != "void").first()
            if inv is None and today >= pe - timedelta(days=s.invoice_days_before):
                inv = issue_invoice(sub, pe, plan=plan, cycle=cycle, today=today, due_on=max(pe, today))
                totals["invoices"] += 1
            if today >= pe and (inv is None or inv.status != "paid") and sub.status in (Subscription.TRIAL,
                                                                                         Subscription.ACTIVE):
                sub.status = Subscription.PAST_DUE
                sub.past_due_since = pe
                if sub.current_period_end is None or as_date(sub.current_period_end) < pe:
                    sub.current_period_end = to_dt(pe)
                audit.record("billing.past_due", "Payment overdue", entity=sub, organization_id=org.id)
                notify(billing_admins(org), "billing", "ZENTAVA payment overdue",
                       f"Pay before {pe + timedelta(days=s.grace_days):%d %b %Y} to keep full access.",
                       "billing.index", organization_id=org.id, exclude_current=False,
                       dedupe_key=f"sub-pastdue-{sub.id}-{pe}", org_slug=org.slug)
                totals["past_due"] += 1
            if sub.status == Subscription.PAST_DUE and today >= (sub.past_due_since or pe) + timedelta(days=s.grace_days):
                sub.status = Subscription.EXPIRED
                audit.record("billing.expired", "Unpaid after the grace period: workspace read-only", entity=sub,
                             organization_id=org.id)
                notify(billing_admins(org), "billing", "ZENTAVA workspace is now read-only",
                       "Pay the open invoice on the Billing page to restore full access.", "billing.index",
                       organization_id=org.id, exclude_current=False, dedupe_key=f"sub-expired-{sub.id}-{pe}",
                       org_slug=org.slug)
                totals["expired"] += 1
            if inv is not None and inv.status == "open" and inv.due_on <= today + timedelta(days=3):
                sent = notify(billing_admins(org), "reminder", f"Invoice {inv.number} is due {inv.due_on:%d %b %Y}",
                              f"{inv.currency} {inv.total:,.2f}", "billing.index", organization_id=org.id,
                              exclude_current=False, dedupe_key=f"inv-due-{inv.id}-{inv.due_on}", org_slug=org.slug)
                totals["reminders"] += sent
            db.session.commit()
        finally:
            clear_tenant()
            g.pop("tenant", None)
    return totals


def payments_configured():
    return bool(current_app.config.get("PAYSTACK_SECRET_KEY"))
