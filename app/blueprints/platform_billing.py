"""Kayron side of billing: all invoices, recording transfers, voiding, issuing, settings and the daily run."""
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, select

from app import audit
from app.billing import issue_invoice, period_end, record_payment, run as run_billing
from app.billing_pdf import invoice_pdf
from app.extensions import db
from app.forms import ActionForm
from app.forms_billing import BillingSettingsForm, ManualPaymentForm, VoidForm
from app.models import Organization, PlatformRole, Subscription
from app.models.billing import BillingSettings, Invoice, Payment
from app.security import platform_required
from app.tenancy import clear_tenant

bp = Blueprint("platform_billing", __name__, url_prefix="/platform/billing")
ADMINS = (PlatformRole.SUPER_ADMIN, PlatformRole.PLATFORM_ADMIN)


@bp.before_request
@login_required
@platform_required()
def _guard():
    clear_tenant()   # Kayron staff only; these pages look across organizations
    return None


@bp.route("/")
@platform_required()
def index():
    status = request.args.get("status") or "open"
    q = Invoice.query
    if status in Invoice.STATUSES:
        q = q.filter(Invoice.status == status)
    if status == "overdue":
        q = q.filter(Invoice.status == "open", Invoice.due_on < date.today())
    invoices = q.order_by(Invoice.due_on.desc(), Invoice.id.desc()).limit(300).all()
    month = date.today().replace(day=1)
    received = db.session.execute(select(Payment.currency, func.sum(Payment.amount)).where(
        Payment.status == "succeeded", Payment.received_on >= month).group_by(Payment.currency)).all()
    outstanding = {}
    for inv in Invoice.query.filter_by(status="open"):
        outstanding[inv.currency] = outstanding.get(inv.currency, Decimal(0)) + inv.balance
    attention = Subscription.query.filter(Subscription.status.in_((Subscription.PAST_DUE, Subscription.EXPIRED))).all()
    return render_template("platform/billing.html", invoices=invoices, status=status, received=received,
                           outstanding=outstanding, attention=attention, action_form=ActionForm(),
                           can_admin=current_user.platform_role in ADMINS, today=date.today())


@bp.route("/invoices/<int:iid>")
@platform_required()
def invoice(iid):
    inv = db.get_or_404(Invoice, iid)
    form = ManualPaymentForm()
    form.received_on.data = date.today()
    form.amount.data = inv.balance
    return render_template("platform/invoice.html", inv=inv, form=form, void_form=VoidForm(),
                           can_admin=current_user.platform_role in ADMINS)


@bp.route("/invoices/<int:iid>.pdf")
@platform_required()
def invoice_download(iid):
    inv = db.get_or_404(Invoice, iid)
    return Response(invoice_pdf(inv, BillingSettings.get()), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{inv.number}.pdf"'})


@bp.route("/invoices/<int:iid>/payment", methods=["POST"])
@platform_required(*ADMINS)
def record(iid):
    inv = db.get_or_404(Invoice, iid)
    form = ManualPaymentForm()
    back = redirect(url_for("platform_billing.invoice", iid=inv.id))
    if inv.status != "open":
        flash("Only open invoices can take payments.", "danger")
        return back
    if not form.validate_on_submit():
        flash("Check the payment: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
        return back
    if form.amount.data > inv.balance:
        flash(f"The balance is {inv.currency} {inv.balance:,.2f}; record at most that.", "danger")
        return back
    if form.received_on.data > date.today():
        flash("The date cannot be in the future.", "danger")
        return back
    if Payment.query.filter_by(reference=form.reference.data).first():
        flash("A payment with this reference is already recorded.", "danger")
        return back
    record_payment(inv, form.method.data, form.amount.data, form.reference.data, received_on=form.received_on.data,
                   recorded_by=current_user, note=form.note.data or None)
    db.session.commit()
    flash("Payment recorded." + (" The invoice is paid and the subscription extended." if inv.status == "paid" else ""),
          "success")
    return back


@bp.route("/invoices/<int:iid>/void", methods=["POST"])
@platform_required(*ADMINS)
def void(iid):
    inv = db.get_or_404(Invoice, iid)
    form = VoidForm()
    if not form.validate_on_submit():
        flash("Give a reason.", "danger")
    elif inv.status != "open" or inv.amount_paid > 0:
        flash("Only an open invoice with no payments can be cancelled.", "danger")
    else:
        inv.status, inv.void_reason = "void", form.reason.data
        audit.record("billing.invoice_void", f"Invoice {inv.number} cancelled: {form.reason.data}", entity=inv,
                     organization_id=inv.organization_id)
        db.session.commit()
        flash("Invoice cancelled.", "success")
    return redirect(url_for("platform_billing.invoice", iid=inv.id))


@bp.route("/organizations/<int:org_id>/invoice", methods=["POST"])
@platform_required(*ADMINS)
def issue(org_id):
    """Issue the next period's invoice now (for example when a customer asks to pay early)."""
    org = db.get_or_404(Organization, org_id)
    sub = org.subscription
    back = redirect(url_for("platform.organization_detail", org_id=org.id))
    if not ActionForm().validate_on_submit():
        abort(400)
    if sub is None:
        flash("Assign a plan first.", "danger")
        return back
    start = period_end(sub) or date.today()
    plan, cycle = sub.pending_plan or sub.plan, sub.pending_cycle or sub.billing_cycle
    if Invoice.query.filter(Invoice.subscription_id == sub.id, Invoice.period_start == start,
                            Invoice.status != "void").first():
        flash("An invoice for that period already exists.", "warning")
        return back
    from app.billing import price
    if price(plan, cycle) <= 0:
        flash("The plan is free; there is nothing to invoice.", "warning")
        return back
    inv = issue_invoice(sub, start, plan=plan, cycle=cycle, due_on=max(start, date.today() + timedelta(days=7)))
    db.session.commit()
    flash(f"Invoice {inv.number} issued.", "success")
    return redirect(url_for("platform_billing.invoice", iid=inv.id))


@bp.route("/settings", methods=["GET", "POST"])
@platform_required(PlatformRole.SUPER_ADMIN)
def settings():
    s = BillingSettings.get(create=True)
    form = BillingSettingsForm(obj=s)
    if form.validate_on_submit():
        form.populate_obj(s)
        audit.record("billing.settings", "Billing settings updated")
        db.session.commit()
        flash("Billing settings saved. New invoices use them; existing invoices keep what they were issued with.",
              "success")
        return redirect(url_for("platform_billing.settings"))
    db.session.commit()
    return render_template("platform/billing_settings.html", form=form)


@bp.route("/run", methods=["POST"])
@platform_required(*ADMINS)
def run_now():
    if not ActionForm().validate_on_submit():
        abort(400)
    totals = run_billing()
    clear_tenant()
    audit.record("billing.run", "Billing run started by hand", details=totals)
    db.session.commit()
    flash("Billing run finished: " + ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in totals.items() if v)
          if any(totals.values()) else "Billing run finished: nothing to do.", "success")
    return redirect(url_for("platform_billing.index"))
