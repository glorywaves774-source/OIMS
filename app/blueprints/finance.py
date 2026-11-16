"""Organization-wide finance overview: budgets across programmes and projects, what is waiting for approval,
and the exchange rates used to combine currencies."""
from datetime import date
from decimal import Decimal

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app import audit
from app.blueprints.tenant import workspace_blueprint
from app.extensions import db
from app.forms import CURRENCIES, ActionForm
from app.forms_programmes import ExchangeRateForm
from app.fx import Rates, combine
from app.models import ExchangeRate, Expenditure, PurchaseOrder, PurchaseRequest
from app.procurement_logic import po_figures_many, read_only
from app.programme_logic import can_do, can_see, finance_summary, visible_owner_stmt
from app.rbac import can
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("finance", __name__, "/finance")

QUEUE_LIMIT = 50


@bp.route("/")
def overview():
    if not can("finance.view"):
        abort(403)
    owners = [o for k in ("programme", "project") for o in db.session.execute(visible_owner_stmt(k).order_by("code")).scalars()
              if can_see("finance.view", o)]
    rows, totals = [], {}
    for o in owners:
        f = finance_summary(o)
        rows.append({"o": o, "f": f})
        # Projects inside a programme are added separately; the programme row shows only its own lines,
        # so adding every row never counts the same money twice.
        t = totals.setdefault(o.currency, {k: Decimal(0) for k in ("budget", "spent", "committed", "pending",
                                                                   "available")})
        for k in t:
            t[k] += f[k]
    # Work queues. Each shows the oldest QUEUE_LIMIT items and how many there are in all; the full lists are
    # on each programme's or project's finance page.
    approvals, orders, payable = [], [], []
    counts = {"approvals": 0, "orders": 0, "payable": 0}
    me = current_user.id
    for o in owners:
        if not read_only() and can_do("finance.approve", o):
            q = Expenditure.query.filter_by(**{o.fk: o.id}, status="pending").filter(
                or_(Expenditure.recorded_by_id.is_(None), Expenditure.recorded_by_id != me))
            counts["approvals"] += q.count()
            if len(approvals) < QUEUE_LIMIT:
                approvals += [(o, e) for e in q.order_by(Expenditure.spent_on, Expenditure.id)
                              .limit(QUEUE_LIMIT - len(approvals))]
            reqs = select(PurchaseRequest.id).where(getattr(PurchaseRequest, o.fk) == o.id)
            q = PurchaseOrder.query.filter(PurchaseOrder.request_id.in_(reqs), PurchaseOrder.status == "draft",
                                           or_(PurchaseOrder.created_by_id.is_(None), PurchaseOrder.created_by_id != me))
            counts["orders"] += q.count()
            if len(orders) < QUEUE_LIMIT:
                orders += [(o, po) for po in q.options(selectinload(PurchaseOrder.items))
                           .order_by(PurchaseOrder.id).limit(QUEUE_LIMIT - len(orders))]
        if can_do("finance.record", o):
            reqs = select(PurchaseRequest.id).where(getattr(PurchaseRequest, o.fk) == o.id)
            pos = PurchaseOrder.query.filter(PurchaseOrder.request_id.in_(reqs), PurchaseOrder.status.in_(
                ("partially_received", "received"))).options(selectinload(PurchaseOrder.items)) \
                .order_by(PurchaseOrder.id).all()
            figs = po_figures_many(pos)
            due = [(o, po, figs[po.id]) for po in pos if figs[po.id]["payable"] > 0]
            counts["payable"] += len(due)
            payable += due[:max(0, QUEUE_LIMIT - len(payable))]
    # Several currencies (or one that is not the main one): one combined total in the main currency
    base, combined, missing, rates_on = g.tenant.currency, None, [], date.today()
    if totals and (len(totals) > 1 or base not in totals):
        combined, missing = combine(totals, base, Rates(), rates_on,
                                    keys=["budget", "spent", "committed", "available"])
    from app import dashboards
    charts = []
    if owners:
        fx = Rates()
        c = dashboards.budget_use([o for o in owners if o.status in ("approved", "active")])
        if c["rows"]:
            charts.append(c)
        c = dashboards.spending_per_month(owners, base, fx)
        if c["rows"]:
            charts.append(c)
    return render_template("finance/overview.html", charts=charts, rows=rows, totals=totals, approvals=approvals,
                           orders=orders,
                           payable=payable, counts=counts, limit=QUEUE_LIMIT, base=base, combined=combined,
                           missing=missing, rates_on=rates_on)


# --- exchange rates -----------------------------------------------------------------------------

def _can_set_rates():
    return not read_only() and can("finance.rates")


@bp.route("/rates", methods=["GET", "POST"])
def rates():
    if not (can("finance.view") or can("finance.rates")):
        abort(403)
    base = g.tenant.currency
    form = ExchangeRateForm()
    form.currency.choices = [(c, label) for c, label in CURRENCIES if c != base]
    if request.method == "POST":
        if not _can_set_rates():
            abort(403)
        if form.validate_on_submit():
            exists = ExchangeRate.query.filter_by(currency=form.currency.data, base_currency=base,
                                                  effective_on=form.effective_on.data).first()
            if exists:
                form.effective_on.errors.append("There is already a rate for this currency on this day. "
                                                "Remove it first if it was wrong.")
            else:
                r = ExchangeRate(currency=form.currency.data, base_currency=base, rate=form.rate.data,
                                 effective_on=form.effective_on.data, source=form.source.data or None,
                                 created_by_id=current_user.id)
                db.session.add(r)
                db.session.flush()
                audit.record("exchange_rate.added", f"Exchange rate 1 {r.currency} = {r.rate:f} {base} from "
                             f"{r.effective_on:%d %b %Y}", entity=r)
                db.session.commit()
                flash(f"Rate saved: 1 {r.currency} = {_fmt_rate(r.rate)} {base} from {r.effective_on:%d %b %Y}.",
                      "success")
                return redirect(url_for("finance.rates"))
    elif not form.effective_on.data:
        form.effective_on.data = date.today()
    fx = Rates()
    current = []
    for c, label in CURRENCIES:
        if c == base:
            continue
        row = fx.latest(c, base)
        current.append({"currency": c, "label": label, "row": row})
    history = ExchangeRate.query.order_by(ExchangeRate.effective_on.desc(), ExchangeRate.id.desc()).limit(100).all()
    used = _currencies_in_use()
    return render_template("finance/rates.html", form=form, base=base, current=current, history=history,
                           used=used, can_set=_can_set_rates(), fmt_rate=_fmt_rate, action_form=ActionForm())


@bp.route("/rates/<int:rid>/delete", methods=["POST"])
def rate_delete(rid):
    if not _can_set_rates():
        abort(403)
    r = tenant_get_or_404(ExchangeRate, rid)
    audit.record("exchange_rate.removed", f"Exchange rate 1 {r.currency} = {r.rate:f} {r.base_currency} from "
                 f"{r.effective_on:%d %b %Y} removed", entity=r)
    db.session.delete(r)
    db.session.commit()
    flash("Rate removed.", "success")
    return redirect(url_for("finance.rates"))


def _fmt_rate(v):
    """Up to 8 decimals without trailing zeros: 15.4, 0.0645, 1600."""
    s = f"{Decimal(v):,.8f}".rstrip("0").rstrip(".")
    return s


def _currencies_in_use():
    """Currencies of programmes and projects (where a rate is needed to combine totals)."""
    from app.models import Programme, Project
    cur = set(db.session.execute(select(Programme.currency).where(Programme.organization_id == g.tenant.id))
              .scalars())
    cur |= set(db.session.execute(select(Project.currency).where(Project.organization_id == g.tenant.id)).scalars())
    return sorted(cur - {g.tenant.currency})
