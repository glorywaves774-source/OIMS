"""Organization-wide finance overview: budgets across programmes and projects, and what is waiting for approval."""
from decimal import Decimal

from flask import abort, render_template
from flask_login import current_user

from app.blueprints.tenant import workspace_blueprint
from app.extensions import db
from app.models import Expenditure, PurchaseOrder, PurchaseRequest
from app.procurement_logic import po_figures, read_only
from app.programme_logic import can_do, can_see, finance_summary, visible_owner_stmt
from app.rbac import can

bp = workspace_blueprint("finance", __name__, "/finance")


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
    approvals, orders, payable = [], [], []
    for o in owners:
        if not read_only() and can_do("finance.approve", o):
            approvals += [(o, e) for e in Expenditure.query.filter_by(**{o.fk: o.id}, status="pending")
                          .order_by(Expenditure.spent_on) if e.recorded_by_id != current_user.id]
            reqs = PurchaseRequest.query.filter_by(**{o.fk: o.id}).with_entities(PurchaseRequest.id)
            orders += [(o, po) for po in PurchaseOrder.query.filter(PurchaseOrder.request_id.in_(reqs),
                                                                     PurchaseOrder.status == "draft")
                       if po.created_by_id != current_user.id]
        if can_do("finance.record", o):
            reqs = PurchaseRequest.query.filter_by(**{o.fk: o.id}).with_entities(PurchaseRequest.id)
            for po in PurchaseOrder.query.filter(PurchaseOrder.request_id.in_(reqs),
                                                 PurchaseOrder.status.in_(("partially_received", "received"))):
                fig = po_figures(po)
                if fig["payable"] > 0:
                    payable.append((o, po, fig))
    return render_template("finance/overview.html", rows=rows, totals=totals, approvals=approvals, orders=orders,
                           payable=payable)
