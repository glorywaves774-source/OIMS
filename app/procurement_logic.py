"""Who may see and act on purchase requests, orders and assets; procurement method; payment figures."""
from decimal import Decimal

from flask import g
from flask_login import current_user
from sqlalchemy import false, func, or_, select, true

from app.extensions import db
from app.meal_logic import owner_ids, owner_in_scope
from app.models import Asset, Expenditure, PurchaseOrder, PurchaseRequest
from app.rbac import DEPT, ORG, can, scope_of

LIVE_OWNER = ("approved", "active", "on_hold")   # programmes/projects that may buy things


def read_only():
    return g.get("support_request") is not None


def method_for(amount, org=None):
    org = org or g.tenant
    amount = Decimal(amount or 0)
    if amount >= Decimal(org.proc_tender_threshold):
        return "tender"
    if amount >= Decimal(org.proc_quotes_threshold):
        return "quotes"
    return "single"


# --- purchase requests ------------------------------------------------------------------------

def _owner_clause(model, scope):
    progs, projs = owner_ids(scope)
    return or_(model.programme_id.in_(progs), model.project_id.in_(projs))


def request_clause(code="procurement.view"):
    scope = scope_of(code)
    if scope == ORG:
        return true()
    if scope is None:
        return false()
    return or_(PurchaseRequest.requested_by_id == current_user.id, _owner_clause(PurchaseRequest, scope))


def visible_requests_stmt(code="procurement.view"):
    return select(PurchaseRequest).where(PurchaseRequest.organization_id == g.tenant.id, request_clause(code))


def can_see_request(pr):
    if pr.requested_by_id == current_user.id:
        return True
    return can("procurement.view") and owner_in_scope("procurement.view", pr.owner)


def can_request_for(owner):
    return (not read_only() and owner is not None and owner.status in LIVE_OWNER and can("procurement.request")
            and owner_in_scope("procurement.request", owner))


def can_approve_request(pr):
    return (not read_only() and can("procurement.approve") and owner_in_scope("procurement.approve", pr.owner)
            and pr.requested_by_id != current_user.id)


def can_process():
    """Quotations, orders, goods received and suppliers (procurement office)."""
    return not read_only() and can("procurement.manage")


def po_paid(po, statuses=("approved",)):
    return Decimal(db.session.scalar(select(func.coalesce(func.sum(Expenditure.amount), 0)).where(
        Expenditure.purchase_order_id == po.id, Expenditure.kind == "expenditure",
        Expenditure.status.in_(statuses))) or 0)


def po_figures(po):
    total = po.total
    paid = po_paid(po)
    pending = po_paid(po, ("pending",))
    received = po.received_value
    return {"total": total, "received": received, "paid": paid, "pending": pending,
            "payable": max(Decimal(0), received - paid - pending), "unpaid": total - paid}


def po_figures_many(pos):
    """po_figures for many orders at once: two queries in total instead of three per order.

    The orders' items should already be loaded (selectinload) by the caller's query."""
    ids = [po.id for po in pos]
    paid = {}
    for i in range(0, len(ids), 900):   # stay below database parameter limits
        for po_id, status, amount in db.session.execute(
                select(Expenditure.purchase_order_id, Expenditure.status, func.sum(Expenditure.amount))
                .where(Expenditure.purchase_order_id.in_(ids[i:i + 900]), Expenditure.kind == "expenditure",
                       Expenditure.status.in_(("approved", "pending")))
                .group_by(Expenditure.purchase_order_id, Expenditure.status)):
            paid[(po_id, status)] = Decimal(amount or 0)
    out = {}
    for po in pos:
        total, received = po.total, po.received_value
        p, pend = paid.get((po.id, "approved"), Decimal(0)), paid.get((po.id, "pending"), Decimal(0))
        out[po.id] = {"total": total, "received": received, "paid": p, "pending": pend,
                      "payable": max(Decimal(0), received - p - pend), "unpaid": total - p}
    return out


def open_orders_for(owner):
    """Orders of a programme/project that are approved but not yet closed (for the closure checklist)."""
    reqs = select(PurchaseRequest.id).where(getattr(PurchaseRequest, owner.fk) == owner.id)
    return PurchaseOrder.query.filter(PurchaseOrder.request_id.in_(reqs),
                                      PurchaseOrder.status.in_(("draft", "approved", "partially_received",
                                                                "received"))).count()


# --- assets ----------------------------------------------------------------------------------

def asset_clause(code="assets.view"):
    scope = scope_of(code)
    if scope == ORG:
        return true()
    if scope is None:
        return false()
    conds = [Asset.custodian_id == current_user.id, _owner_clause(Asset, scope)]
    if scope == DEPT:
        from app.blueprints.tenant import my_department_id
        if my_department_id():
            conds.append(Asset.department_id == my_department_id())
    return or_(*conds)


def visible_assets_stmt(code="assets.view"):
    return select(Asset).where(Asset.organization_id == g.tenant.id, asset_clause(code))


def can_see_asset(a):
    return db.session.scalar(select(func.count()).select_from(Asset).where(Asset.id == a.id, asset_clause())) > 0


def can_manage_asset(a=None):
    return not read_only() and can("assets.manage") and (a is None or a.status != "disposed")


def open_assets_for(owner):
    """Assets still charged to a programme/project (for the closure checklist)."""
    return Asset.query.filter(getattr(Asset, owner.fk) == owner.id, Asset.status != "disposed").count()
