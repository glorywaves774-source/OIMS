"""Billing inside an organization's workspace: plan, usage, invoices, online payment, plan changes.

Also the Paystack webhook (public, signed), which confirms payments even if the person closes the
browser before returning.
"""
import secrets
from datetime import date

from flask import (Blueprint, Response, abort, current_app, flash, g, make_response, redirect, render_template,
                   request, url_for)
from flask_login import current_user

from app import audit, paystack
from app.billing import (billing_admins, issue_invoice, period_end, price, record_payment, state as billing_state)
from app.billing_pdf import invoice_pdf
from app.blueprints.documents import storage_used_bytes
from app.blueprints.tenant import workspace_blueprint
from app.extensions import csrf, db
from app.forms import ActionForm
from app.forms_billing import ChangePlanForm
from app.models import Membership, Subscription, SubscriptionPlan
from app.models.billing import BillingSettings, Invoice, Payment
from app.notify import notify
from app.rbac import can, require_permission
from app.security import csp_allowing_form_target
from app.tenancy import clear_tenant, set_tenant, tenant_get_or_404

bp = workspace_blueprint("billing", __name__, "/billing")
hooks = Blueprint("billing_hooks", __name__, url_prefix="/billing-webhooks")


def _manage():
    return can("billing.manage") and g.get("support_request") is None


def usage(org):
    users = Membership.query.filter(Membership.organization_id == org.id,
                                    Membership.status != Membership.SUSPENDED).count()
    return {"users": users, "storage_mb": round(storage_used_bytes(org.id) / (1024 * 1024), 1)}


def fits(plan, use):
    problems = []
    if plan.max_users is not None and use["users"] > plan.max_users:
        problems.append(f"{use['users']} people use the workspace, the {plan.name} plan allows {plan.max_users}")
    if plan.max_storage_mb is not None and use["storage_mb"] > plan.max_storage_mb:
        problems.append(f"{use['storage_mb']:g} MB of files are stored, the {plan.name} plan allows "
                        f"{plan.max_storage_mb} MB")
    return problems


@bp.route("/")
@require_permission("billing.view")
def index():
    org = g.tenant
    sub = org.subscription
    use = usage(org)
    invoices = Invoice.query.filter_by(organization_id=org.id).order_by(Invoice.issued_on.desc(), Invoice.id.desc()).all()
    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.monthly_price).all()
    plans = [p for p in plans if p.is_public or (sub and p.id == sub.plan_id)]
    form = ChangePlanForm()
    form.plan_id.choices = [(p.id, p.name) for p in plans]
    if sub:
        form.plan_id.data = sub.pending_plan_id or sub.plan_id
        form.billing_cycle.data = sub.pending_cycle or sub.billing_cycle
    online = paystack.configured()
    resp = make_response(render_template("billing/index.html", sub=sub, st=billing_state(org), use=use, invoices=invoices,
                           plans=plans, form=form, fits={p.id: fits(p, use) for p in plans},
                           can_manage=_manage(), online=online, settings=BillingSettings.get(),
                           period_end=period_end(sub) if sub else None, action_form=ActionForm(), today=date.today()))
    if online:   # the Pay online button leads on to Paystack's checkout page
        resp.headers["Content-Security-Policy"] = csp_allowing_form_target(paystack.CHECKOUT_ORIGIN)
    return resp


@bp.route("/plan", methods=["POST"])
def change_plan():
    if not _manage():
        abort(403)
    org, sub = g.tenant, g.tenant.subscription
    if sub is None:
        flash("This workspace has no subscription yet. Contact Kayron.", "danger")
        return redirect(url_for("billing.index"))
    form = ChangePlanForm()
    form.plan_id.choices = [(p.id, p.name) for p in SubscriptionPlan.query.filter_by(is_active=True)]
    if not form.validate_on_submit():
        flash("Choose a plan.", "danger")
        return redirect(url_for("billing.index"))
    plan = db.session.get(SubscriptionPlan, form.plan_id.data)
    if not plan.is_public and plan.id != sub.plan_id:
        abort(400)
    problems = fits(plan, usage(org))
    if problems:
        flash("This plan is too small: " + "; ".join(problems) + ".", "danger")
        return redirect(url_for("billing.index"))
    cycle = form.billing_cycle.data
    same = plan.id == sub.plan_id and cycle == sub.billing_cycle
    if sub.status == Subscription.TRIAL:
        # During a free trial the choice applies straight away; the first invoice uses it.
        sub.plan_id, sub.billing_cycle, sub.pending_plan_id, sub.pending_cycle = plan.id, cycle, None, None
        msg = f"You are now on the {plan.name} plan. Your trial continues until it ends."
    elif same:
        sub.pending_plan_id, sub.pending_cycle = None, None
        msg = "You will stay on your current plan."
    else:
        sub.pending_plan_id, sub.pending_cycle = plan.id, cycle
        msg = f"The {plan.name} plan ({'yearly' if cycle == 'annual' else 'monthly'}) starts with the next period."
    # An unpaid invoice for the coming (or lapsed) period is reissued with the new choice.
    inv = Invoice.query.filter_by(subscription_id=sub.id, status="open").order_by(Invoice.period_start.desc()).first()
    if inv is not None and not inv.payments and (inv.plan_id != plan.id or inv.billing_cycle != cycle):
        inv.status, inv.void_reason = "void", "Replaced after a change of plan"
        if price(plan, cycle) > 0:
            issue_invoice(sub, inv.period_start, plan=plan, cycle=cycle, due_on=inv.due_on)
        elif sub.status in (Subscription.PAST_DUE, Subscription.EXPIRED):
            sub.plan_id, sub.billing_cycle, sub.pending_plan_id, sub.pending_cycle = plan.id, cycle, None, None
            sub.status, sub.past_due_since = Subscription.ACTIVE, None
            msg = f"You are now on the free {plan.name} plan."
        msg += " The open invoice was replaced."
    audit.record("billing.plan_changed", f"Plan choice: {plan.name} ({cycle})", entity=sub, organization_id=org.id)
    db.session.commit()
    flash(msg, "success")
    return redirect(url_for("billing.index"))


@bp.route("/<any(cancel, resume):action>", methods=["POST"])
def cancel(action):
    if not _manage() or not ActionForm().validate_on_submit():
        abort(403)
    sub = g.tenant.subscription
    if sub is None or sub.status in (Subscription.CANCELLED, Subscription.EXPIRED):
        abort(400)
    sub.cancel_at_period_end = action == "cancel"
    audit.record(f"billing.{action}", "Subscription set to end at the period end" if action == "cancel"
                 else "Subscription will continue", entity=sub, organization_id=g.tenant.id)
    notify(billing_admins(g.tenant), "billing",
           "Subscription set to end" if action == "cancel" else "Subscription will continue",
           f"Changed by {current_user.full_name}", "billing.index")
    db.session.commit()
    pe = period_end(sub)
    flash(f"The subscription will end on {pe:%d %b %Y}; the workspace then becomes read-only." if action == "cancel"
          and pe else "The subscription will continue.", "success")
    return redirect(url_for("billing.index"))


def _invoice(iid):
    inv = tenant_get_or_404(Invoice, iid)
    return inv


@bp.route("/invoices/<int:iid>.pdf")
@require_permission("billing.view")
def invoice_download(iid):
    inv = _invoice(iid)
    return Response(invoice_pdf(inv, BillingSettings.get()), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{inv.number}.pdf"'})


@bp.route("/invoices/<int:iid>/pay", methods=["POST"])
def pay(iid):
    """Start an online payment with Paystack for the invoice balance."""
    if not _manage() or not ActionForm().validate_on_submit():
        abort(403)
    inv = _invoice(iid)
    if inv.status != "open" or inv.balance <= 0:
        flash("This invoice has nothing left to pay.", "info")
        return redirect(url_for("billing.index"))
    if not paystack.configured():
        flash("Online payment is not available. Please pay by transfer using the details shown.", "warning")
        return redirect(url_for("billing.index"))
    reference = f"{inv.number}-{secrets.token_hex(5)}"
    p = Payment(organization_id=inv.organization_id, invoice_id=inv.id, method="paystack", reference=reference,
                amount=inv.balance, currency=inv.currency, status="pending", started_by_id=current_user.id)
    db.session.add(p)
    try:
        url = paystack.initialize(email=g.tenant.email, amount=inv.balance, currency=inv.currency, reference=reference,
                                  callback_url=url_for("billing.paystack_return", _external=True),
                                  metadata={"invoice": inv.number, "organization": g.tenant.slug})
    except paystack.PaystackError as exc:
        db.session.rollback()
        flash(f"The payment could not be started: {exc}", "danger")
        return redirect(url_for("billing.index"))
    audit.record("billing.payment_started", f"Online payment started for {inv.number}", entity=inv,
                 organization_id=inv.organization_id)
    db.session.commit()
    return redirect(url)


def _confirm(p, data):
    """Apply a verified Paystack transaction to its pending payment. Returns True if it is now paid."""
    if data.get("status") != "success":
        if p.status == "pending" and data.get("status") in ("failed", "abandoned", "reversed"):
            p.status, p.provider_status = "failed", data.get("status")
        return False
    if (data.get("currency") or "").upper() != p.currency or int(data.get("amount") or 0) < paystack.to_subunit(p.amount):
        p.status, p.provider_status = "failed", "amount_mismatch"
        audit.record("billing.payment_mismatch", f"{p.reference}: amount or currency does not match",
                     organization_id=p.organization_id)
        return False
    record_payment(p.invoice, "paystack", p.amount, p.reference, channel=data.get("channel"),
                   provider_status="success")
    return True


@bp.route("/paystack/return")
@require_permission("billing.view")
def paystack_return():
    ref = request.args.get("reference") or request.args.get("trxref") or ""
    p = Payment.query.filter_by(reference=ref).first()
    if p is None:
        abort(404)
    if p.status == "succeeded":
        flash("Payment received. Thank you!", "success")
        return redirect(url_for("billing.index"))
    try:
        ok = _confirm(p, paystack.verify(ref))
    except paystack.PaystackError as exc:
        flash(f"We could not confirm the payment yet ({exc}). If money was taken it will be recorded automatically "
              "within a few minutes.", "warning")
        return redirect(url_for("billing.index"))
    db.session.commit()
    flash("Payment received. Thank you!" if ok else "The payment was not completed.", "success" if ok else "warning")
    return redirect(url_for("billing.index"))


@hooks.route("/paystack", methods=["POST"])
@csrf.exempt
def paystack_webhook():
    raw = request.get_data()
    if not paystack.signature_ok(raw, request.headers.get("x-paystack-signature")):
        abort(401)
    event = request.get_json(silent=True) or {}
    if event.get("event") != "charge.success":
        return {"ok": True}
    ref = (event.get("data") or {}).get("reference") or ""
    from app.tenancy import unscoped
    from sqlalchemy import select
    p = db.session.execute(unscoped(select(Payment).where(Payment.reference == ref))).scalar_one_or_none()
    if p is None:
        return {"ok": True}   # not one of ours
    set_tenant(p.organization_id)
    g.tenant = p.invoice.organization
    try:
        if p.status != "succeeded":
            # Never trust the webhook body for the amount: ask Paystack.
            _confirm(p, paystack.verify(ref))
            db.session.commit()
    except paystack.PaystackError:
        db.session.rollback()
        current_app.logger.warning("Paystack verification failed for %s; Paystack will retry", ref)
        return {"ok": False}, 503
    finally:
        clear_tenant()
        g.pop("tenant", None)
    return {"ok": True}
