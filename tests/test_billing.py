"""Phase 8: SaaS billing — invoices, renewals, grace period, read-only lock, payments, plan changes."""
import hashlib
import hmac
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import (AuditLog, Membership, Notification, Organization, PlatformRole, Subscription,
                        SubscriptionPlan, Task)
from app.models.billing import BillingSettings, Invoice, Payment
from tests.conftest import add_member, login, logout, make_org, make_staff

T = date.today()


def dt(d):
    return datetime.combine(d, time(0), tzinfo=timezone.utc)


@pytest.fixture
def env(app, db):
    basic = SubscriptionPlan(code="basic", name="Basic", currency="GHS", monthly_price=Decimal("100"),
                             annual_price=Decimal("1000"), max_users=10, max_storage_mb=500)
    small = SubscriptionPlan(code="small", name="Small", currency="GHS", monthly_price=Decimal("40"),
                             annual_price=Decimal("400"), max_users=2)
    free = SubscriptionPlan(code="free", name="Free", currency="GHS", monthly_price=0, annual_price=0, max_users=20)
    hidden = SubscriptionPlan(code="custom", name="Custom", currency="GHS", monthly_price=Decimal("5"),
                              annual_price=Decimal("50"), is_public=False)
    db.session.add_all([basic, small, free, hidden])
    db.session.commit()
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    people = {"org": o, "admin": admin, "basic": basic, "small": small, "free": free, "hidden": hidden}
    for key, role in [("ed", "Executive Director"), ("fin", "Finance Officer"), ("staff", "Staff Member")]:
        u, _ = add_member(o, f"{key}@hope.org", role_name=role)
        people[key] = u
    sub = Subscription(organization_id=o.id, plan_id=basic.id, status=Subscription.ACTIVE, billing_cycle="monthly",
                       starts_at=dt(T - timedelta(days=23)), current_period_end=dt(T + timedelta(days=7)))
    db.session.add(sub)
    s = BillingSettings.get(create=True)
    s.tax_label, s.tax_rate, s.bank_details = "VAT", Decimal("15"), "Ecobank, account 0012345, HOLIDO"
    db.session.commit()
    make_staff("billing@holido.org", PlatformRole.PLATFORM_ADMIN)
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    make_staff("super@holido.org", PlatformRole.SUPER_ADMIN)
    people["sub"] = sub
    return people


def W(env, path=""):
    return f"/o/{env['org'].slug}{path}"


def as_(client, email):
    logout(client)
    login(client, email if "@" in email else f"{email}@hope.org")


def run(app, today):
    from app.billing import run as run_billing
    from app.tenancy import clear_tenant
    with app.test_request_context("/"):
        totals = run_billing(today=today)
    clear_tenant()
    return totals


def fresh(db, model, ident):
    db.session.expire_all()
    return db.session.get(model, ident)


def test_invoice_renewal_grace_and_read_only_lock(client, app, env, db):
    sub = env["sub"]
    assert run(app, T - timedelta(days=1))["invoices"] == 0           # 8 days before: too early
    assert run(app, T)["invoices"] == 1                                # 7 days before the period ends
    assert run(app, T)["invoices"] == 0                                # never twice
    inv = Invoice.query.one()
    assert inv.number == f"ZTV-{T.year}-00001" and inv.total == Decimal("115.00") and inv.tax_amount == Decimal("15.00")
    assert inv.period_start == T + timedelta(days=7) and inv.due_on == T + timedelta(days=7)
    assert inv.bill_to["name"] == "Hope Trust" and inv.issuer["name"].startswith("HOLIDO")
    assert Notification.query.filter_by(user_id=env["admin"].id, kind="billing").count() == 1
    as_(client, "admin")
    html = client.get(W(env, "/billing/")).data.decode()
    assert inv.number in html and "Ecobank" in html and "Pay online" not in html   # Paystack not configured
    # the period ends unpaid: past due, full access, warning
    assert run(app, T + timedelta(days=7))["past_due"] == 1
    assert fresh(db, Subscription, sub.id).status == "past_due"
    html = client.get(W(env, "/")).data.decode()
    assert "Payment is overdue" in html
    assert client.post(W(env, "/tasks/new"), data={"title": "Still works", "priority": "normal"}).status_code == 302
    # grace period over: read-only
    assert run(app, T + timedelta(days=21))["expired"] == 1
    assert fresh(db, Subscription, sub.id).status == "expired"
    tasks_before = Task.query.count()
    r = client.post(W(env, "/tasks/new"), data={"title": "Blocked", "priority": "normal"})
    assert r.status_code == 403 and b"Changes are paused" in r.data and Task.query.count() == tasks_before
    assert client.get(W(env, "/tasks/")).status_code == 200            # reading still works
    assert client.get(W(env, "/billing/")).status_code == 200
    as_(client, "staff")
    html = client.get(W(env, "/")).data.decode()
    assert "read-only" in html and "Billing</a>" not in html            # everyone sees why, only admins get the link
    # HOLIDO records the bank transfer: paid, subscription restored
    as_(client, "billing@holido.org")
    r = client.post(f"/platform/billing/invoices/{inv.id}/payment", data={
        "method": "bank_transfer", "amount": "115.00", "reference": "ECO-778", "received_on": T.isoformat()},
        follow_redirects=True)
    assert b"The invoice is paid" in r.data
    sub = fresh(db, Subscription, sub.id)
    inv = fresh(db, Invoice, inv.id)
    assert inv.status == "paid" and sub.status == "active" and sub.past_due_since is None
    assert sub.current_period_end.date() == inv.period_end > T
    as_(client, "admin")
    assert client.post(W(env, "/tasks/new"), data={"title": "Back", "priority": "normal"}).status_code == 302


def test_paying_long_after_expiry_restarts_from_today(client, app, env, db):
    sub = env["sub"]
    sub.current_period_end = dt(T - timedelta(days=60))
    db.session.commit()
    run(app, T - timedelta(days=67))
    run(app, T - timedelta(days=60))
    run(app, T - timedelta(days=40))
    sub = fresh(db, Subscription, sub.id)
    assert sub.status == "expired"
    inv = Invoice.query.one()
    from app.billing import record_payment
    with app.test_request_context("/"):
        record_payment(inv, "mobile_money", inv.total, "MOMO-1")
        db.session.commit()
    sub = fresh(db, Subscription, sub.id)
    assert sub.status == "active" and sub.current_period_end.date() > T + timedelta(days=27)


def test_late_payment_within_a_long_grace_keeps_the_billing_cycle(client, app, env, db):
    """With a 60-day grace, an invoice can be paid after its own period ended while still past due (not
    locked). The paid period stays as invoiced, so the cycle does not shift."""
    s = BillingSettings.get()
    s.grace_days = 60
    sub = env["sub"]
    sub.current_period_end = dt(T - timedelta(days=40))
    db.session.commit()
    run(app, T - timedelta(days=47))
    run(app, T - timedelta(days=40))
    assert fresh(db, Subscription, sub.id).status == "past_due"
    inv = Invoice.query.one()
    assert inv.period_end < T
    from app.billing import record_payment
    with app.test_request_context("/"):
        record_payment(inv, "bank_transfer", inv.total, "TRF-LATE")
        db.session.commit()
    sub = fresh(db, Subscription, sub.id)
    assert sub.status == "active" and sub.current_period_end.date() == inv.period_end   # not "a month from today"
    run(app, T)   # the next period is owed straight away
    assert Invoice.query.filter_by(status="open").one().period_start == inv.period_end


def test_trial_and_free_plans(client, app, env, db):
    sub = env["sub"]
    sub.status, sub.trial_ends_at, sub.current_period_end = Subscription.TRIAL, dt(T + timedelta(days=5)), None
    db.session.commit()
    run(app, T)
    inv = Invoice.query.one()
    assert inv.period_start == T + timedelta(days=5)
    as_(client, "admin")
    r = client.post(W(env, "/billing/plan"), data={"plan_id": env["free"].id, "billing_cycle": "monthly"},
                    follow_redirects=True)
    assert b"now on the Free plan" in r.data and b"open invoice was replaced" in r.data
    assert fresh(db, Invoice, inv.id).status == "void"
    totals = run(app, T + timedelta(days=5))
    sub = fresh(db, Subscription, sub.id)
    assert totals["free_renewed"] == 1 and sub.status == "active" and Invoice.query.filter_by(status="open").count() == 0


def test_plan_change_waits_for_next_period_and_respects_limits(client, app, env, db):
    run(app, T)
    old = Invoice.query.one()
    as_(client, "admin")
    r = client.post(W(env, "/billing/plan"), data={"plan_id": env["small"].id, "billing_cycle": "monthly"},
                    follow_redirects=True)
    assert b"plan is too small" in r.data                      # 4 people, Small allows 2
    r = client.post(W(env, "/billing/plan"), data={"plan_id": env["basic"].id, "billing_cycle": "annual"},
                    follow_redirects=True)
    assert b"starts with the next period" in r.data
    sub = fresh(db, Subscription, env["sub"].id)
    assert sub.plan_id == env["basic"].id and sub.billing_cycle == "monthly" and sub.pending_cycle == "annual"
    assert fresh(db, Invoice, old.id).status == "void"
    new = Invoice.query.filter_by(status="open").one()
    assert new.total == Decimal("1150.00") and new.period_end.year == new.period_start.year + 1
    assert client.post(W(env, "/billing/plan"), data={"plan_id": env["hidden"].id,
                                                       "billing_cycle": "monthly"}).status_code == 400
    # paying applies the new cycle
    from app.billing import record_payment
    with app.test_request_context("/"):
        record_payment(new, "bank_transfer", new.total, "TRF-1")
        db.session.commit()
    sub = fresh(db, Subscription, env["sub"].id)
    assert sub.billing_cycle == "annual" and sub.pending_cycle is None


def test_cancel_at_period_end(client, app, env, db):
    as_(client, "admin")
    client.post(W(env, "/billing/cancel"), data={})
    assert fresh(db, Subscription, env["sub"].id).cancel_at_period_end
    assert "set to end" in client.get(W(env, "/billing/")).data.decode()
    assert run(app, T + timedelta(days=7))["cancelled"] == 1
    assert fresh(db, Subscription, env["sub"].id).status == "cancelled"
    assert client.post(W(env, "/tasks/new"), data={"title": "x", "priority": "normal"}).status_code == 403


def test_billing_permissions(client, env, db):
    as_(client, "staff")
    assert client.get(W(env, "/billing/")).status_code == 403
    as_(client, "ed")   # can see, cannot change
    assert client.get(W(env, "/billing/")).status_code == 200
    assert client.post(W(env, "/billing/plan"), data={"plan_id": env["free"].id}).status_code == 403
    assert client.post(W(env, "/billing/cancel"), data={}).status_code == 403
    o2, a2 = make_org("Rival Org", admin_email="admin@rival.org")
    from app.tenancy import clear_tenant
    clear_tenant()


def test_invoice_pdf_and_isolation(client, app, env, db):
    run(app, T)
    inv = Invoice.query.one()
    as_(client, "admin")
    r = client.get(W(env, f"/billing/invoices/{inv.id}.pdf"))
    assert r.status_code == 200 and r.data.startswith(b"%PDF")
    o2, _ = make_org("Rival Org", admin_email="admin@rival.org")
    as_(client, "admin@rival.org")
    assert client.get(f"/o/{o2.slug}/billing/invoices/{inv.id}.pdf").status_code == 404


# --- Paystack -------------------------------------------------------------------------------------

@pytest.fixture
def paystack_on(app, monkeypatch):
    app.config["PAYSTACK_SECRET_KEY"] = "sk_test_secret"
    calls = {"verify": {}}
    from app import paystack

    def fake_init(email, amount, currency, reference, callback_url, metadata):
        calls["init"] = {"email": email, "amount": amount, "currency": currency, "reference": reference}
        return "https://checkout.paystack.com/abc"

    def fake_verify(reference):
        return calls["verify"].get(reference) or {"status": "abandoned"}

    monkeypatch.setattr(paystack, "initialize", fake_init)
    monkeypatch.setattr(paystack, "verify", fake_verify)
    yield calls
    app.config["PAYSTACK_SECRET_KEY"] = None


def test_online_payment(client, app, env, db, paystack_on):
    run(app, T)
    inv = Invoice.query.one()
    as_(client, "admin")
    assert "Pay online" in client.get(W(env, "/billing/")).data.decode()
    r = client.post(W(env, f"/billing/invoices/{inv.id}/pay"), data={})
    assert r.status_code == 302 and r.headers["Location"] == "https://checkout.paystack.com/abc"
    call = paystack_on["init"]
    assert call["email"] == env["org"].email and call["amount"] == Decimal("115.00") and call["currency"] == "GHS"
    p = Payment.query.one()
    assert p.status == "pending" and p.reference == call["reference"]
    # not paid (abandoned) → nothing changes
    r = client.get(W(env, f"/billing/paystack/return?reference={p.reference}"), follow_redirects=True)
    assert b"not completed" in r.data and fresh(db, Invoice, inv.id).status == "open"
    # a short payment is refused
    paystack_on["verify"][p.reference] = {"status": "success", "amount": 100, "currency": "GHS"}
    client.get(W(env, f"/billing/paystack/return?reference={p.reference}"))
    assert fresh(db, Payment, p.id).status == "failed" and fresh(db, Invoice, inv.id).status == "open"
    # a new attempt, paid in full
    client.post(W(env, f"/billing/invoices/{inv.id}/pay"), data={})
    p2 = Payment.query.filter_by(status="pending").one()
    paystack_on["verify"][p2.reference] = {"status": "success", "amount": 11500, "currency": "GHS",
                                           "channel": "mobile_money"}
    r = client.get(W(env, f"/billing/paystack/return?reference={p2.reference}"), follow_redirects=True)
    assert b"Payment received" in r.data
    inv = fresh(db, Invoice, inv.id)
    assert inv.status == "paid" and fresh(db, Payment, p2.id).channel == "mobile_money"
    assert Payment.query.filter_by(status="succeeded").count() == 1


def test_paystack_webhook(client, app, env, db, paystack_on):
    run(app, T)
    inv = Invoice.query.one()
    as_(client, "admin")
    client.post(W(env, f"/billing/invoices/{inv.id}/pay"), data={})
    p = Payment.query.one()
    logout(client)
    body = json.dumps({"event": "charge.success", "data": {"reference": p.reference, "amount": 99999999}}).encode()
    assert client.post("/billing-webhooks/paystack", data=body, content_type="application/json",
                       headers={"x-paystack-signature": "wrong"}).status_code == 401
    sig = hmac.new(b"sk_test_secret", body, hashlib.sha512).hexdigest()
    # the webhook body is not trusted: Paystack's own answer (verify) decides
    paystack_on["verify"][p.reference] = {"status": "success", "amount": 11500, "currency": "GHS", "channel": "card"}
    for _ in range(2):   # delivered twice: recorded once
        r = client.post("/billing-webhooks/paystack", data=body, content_type="application/json",
                        headers={"x-paystack-signature": sig})
        assert r.status_code == 200
    assert fresh(db, Invoice, inv.id).status == "paid"
    assert Payment.query.filter_by(status="succeeded").count() == 1
    assert fresh(db, Subscription, env["sub"].id).status == "active"


# --- HOLIDO side -----------------------------------------------------------------------------------

def test_platform_billing(client, app, env, db):
    run(app, T)
    inv = Invoice.query.one()
    as_(client, "support@holido.org")   # can look, cannot act
    assert client.get("/platform/billing/").status_code == 200
    assert client.get(f"/platform/billing/invoices/{inv.id}").status_code == 200
    assert client.post(f"/platform/billing/invoices/{inv.id}/payment", data={}).status_code == 403
    assert client.get("/platform/billing/settings").status_code == 403
    as_(client, "billing@holido.org")
    r = client.post(f"/platform/billing/invoices/{inv.id}/payment", data={
        "method": "bank_transfer", "amount": "200", "reference": "X", "received_on": T.isoformat()},
        follow_redirects=True)
    assert b"record at most that" in r.data
    client.post(f"/platform/billing/invoices/{inv.id}/payment", data={
        "method": "bank_transfer", "amount": "50", "reference": "PART-1", "received_on": T.isoformat()})
    inv = fresh(db, Invoice, inv.id)
    assert inv.status == "open" and inv.balance == Decimal("65.00")
    r = client.post(f"/platform/billing/invoices/{inv.id}/payment", data={
        "method": "bank_transfer", "amount": "10", "reference": "PART-1", "received_on": T.isoformat()},
        follow_redirects=True)
    assert b"already recorded" in r.data
    r = client.post(f"/platform/billing/invoices/{inv.id}/void", data={"reason": "Mistake"}, follow_redirects=True)
    assert b"no payments can be cancelled" in r.data
    # issuing by hand, and the settings page
    org = env["org"]
    r = client.post(f"/platform/billing/organizations/{org.id}/invoice", data={}, follow_redirects=True)
    assert b"already exists" in r.data
    as_(client, "super@holido.org")
    assert client.get("/platform/billing/settings").status_code == 200
    client.post("/platform/billing/settings", data={"company_name": "HOLIDO", "tax_label": "", "tax_rate": "0",
                                                    "invoice_days_before": "10", "grace_days": "7"})
    s = fresh(db, BillingSettings, 1)
    assert s.grace_days == 7 and s.invoice_days_before == 10
    assert client.get(f"/platform/organizations/{org.id}").status_code == 200
    assert client.post("/platform/billing/run", data={}, follow_redirects=True).status_code == 200
    assert AuditLog.query.filter_by(action="billing.payment").count() == 1


def test_free_plan_can_be_created(client, env, db):
    as_(client, "super@holido.org")
    r = client.post("/platform/plans/new", data={"code": "community", "name": "Community", "currency": "GHS",
                                                 "monthly_price": "0", "annual_price": "0", "trial_days": "0",
                                                 "is_active": "y"})
    assert r.status_code == 302
    assert SubscriptionPlan.query.filter_by(code="community").one().monthly_price == 0


def test_manual_arrangements_are_not_invoiced(client, app, env, db):
    sub = env["sub"]
    sub.current_period_end = None
    db.session.commit()
    assert run(app, T)["invoices"] == 0 and Invoice.query.count() == 0
