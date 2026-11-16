"""Organization-wide finance overview: budgets across programmes and projects, and what is waiting for approval."""
from decimal import Decimal

from flask import abort, render_template
from flask_login import current_user
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.blueprints.tenant import workspace_blueprint
from app.extensions import db
from app.models import Expenditure, PurchaseOrder, PurchaseRequest
from app.procurement_logic import po_figures_many, read_only
from app.programme_logic import can_do, can_see, finance_summary, visible_owner_stmt
from app.rbac import can

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
    return render_template("finance/overview.html", rows=rows, totals=totals, approvals=approvals, orders=orders,
                           payable=payable, counts=counts, limit=QUEUE_LIMIT)
