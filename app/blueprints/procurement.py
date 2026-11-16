"""Procurement: suppliers, purchase requests, quotations, purchase orders, goods received and payments."""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app import audit
from app.blueprints.beneficiaries import owner_key, parse_owner
from app.blueprints.tenant import page_arg, workspace_blueprint
from app.crypto import decrypt_text, encrypt_text
from app.extensions import db
from app.forms import ActionForm
from app.forms_procurement import (CancelForm, ItemForm, OrderForm, PaymentForm, QuotationForm, ReceiptForm,
                                   RequestForm, SelectionForm, SupplierForm, SupplierStatusForm, ThresholdForm)
from app.forms_programmes import ReviewNoteForm
from app.models import (Activity, Asset, AssetEvent, BudgetLine, Expenditure, GoodsReceipt, PurchaseOrder,
                        PurchaseOrderItem, PurchaseRequest, PurchaseRequestItem, Quotation, Supplier, utcnow)
from app.notify import next_reference, notify
from app.procurement_logic import (LIVE_OWNER, can_approve_request, can_process, can_request_for, can_see_request,
                                   method_for, po_figures, read_only, visible_requests_stmt)
from app.programme_logic import can_do, holders, line_figures, visible_owner_stmt
from app.rbac import ORG, can, require_permission, scope_of
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("procurement", __name__, "/procurement")
CENT = Decimal("0.01")


def _back(pr, anchor=""):
    return redirect(url_for("procurement.request_detail", rid=pr.id) + anchor)


def _load(rid):
    pr = tenant_get_or_404(PurchaseRequest, rid)
    if not can_see_request(pr):
        abort(404)
    return pr


# ====================================================================================
# Purchase requests
# ====================================================================================

@bp.route("/")
def index():
    if not (can("procurement.view") or can("procurement.request")):
        abort(403)
    status = request.args.get("status") or "open"
    view = request.args.get("view") or "all"
    stmt = visible_requests_stmt()
    if not can("procurement.view"):
        stmt = select(PurchaseRequest).where(PurchaseRequest.requested_by_id == current_user.id)
    if status == "open":
        stmt = stmt.where(PurchaseRequest.status.in_(("draft", "submitted", "approved", "ordered")))
    elif status in PurchaseRequest.STATUSES:
        stmt = stmt.where(PurchaseRequest.status == status)
    if view == "mine":
        stmt = stmt.where(PurchaseRequest.requested_by_id == current_user.id)
    elif view == "approve":
        stmt = stmt.where(PurchaseRequest.status == "submitted")
    page = db.paginate(stmt.order_by(PurchaseRequest.id.desc()), page=page_arg(), per_page=30, error_out=False)
    orders = None
    if can("procurement.view"):
        visible_ids = visible_requests_stmt().with_only_columns(PurchaseRequest.id)
        orders = db.paginate(
            select(PurchaseOrder).where(PurchaseOrder.request_id.in_(visible_ids), PurchaseOrder.status.in_(
                ("draft", "approved", "partially_received", "received")))
            .options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.supplier),
                     selectinload(PurchaseOrder.request))
            .order_by(PurchaseOrder.id.desc()), page=_int_arg("opage"), per_page=30, error_out=False)
    return render_template("procurement/index.html", page=page, status=status, view=view, orders=orders,
                           can_new=bool(_request_owners()), can_process=can_process(),
                           can_settings=can_process() and scope_of("procurement.manage") == ORG)


def _int_arg(name):
    try:
        return max(1, int(request.args.get(name, 1)))
    except ValueError:
        return 1


def _request_owners():
    if read_only() or not can("procurement.request"):
        return []
    return [o for k in ("programme", "project") for o in db.session.execute(
        visible_owner_stmt(k).order_by("code")).scalars() if can_request_for(o)]


def _setup_request(form, owner):
    form.budget_line_id.choices = [(0, "— Choose —")] + [
        (b.id, f"{b.code + ' ' if b.code else ''}{b.description} (available {owner.currency} "
               f"{line_figures(b)['available']:,.2f})")
        for b in BudgetLine.query.filter_by(**{owner.fk: owner.id}).order_by(BudgetLine.code, BudgetLine.id)]
    form.activity_id.choices = [(0, "— None —")] + [(a.id, a.title[:90]) for a in Activity.query.filter_by(
        **{owner.fk: owner.id}).order_by(Activity.planned_start)]


@bp.route("/new", methods=["GET", "POST"])
def new():
    owners = _request_owners()
    if not owners:
        abort(403)
    ov = request.values.get("owner")
    if not ov:
        return render_template("procurement/choose_owner.html", owners=owners)
    owner = parse_owner(ov)
    if not can_request_for(owner):
        abort(403)
    form = RequestForm()
    _setup_request(form, owner)
    if form.validate_on_submit():
        line = tenant_get_or_404(BudgetLine, form.budget_line_id.data)
        if getattr(line, owner.fk) != owner.id:
            abort(400)
        if form.activity_id.data:
            act = tenant_get_or_404(Activity, form.activity_id.data)
            if getattr(act, owner.fk) != owner.id:
                abort(400)
        pr = PurchaseRequest(organization_id=g.tenant.id, code=next_reference("PR"), title=form.title.data,
                             budget_line_id=line.id, activity_id=form.activity_id.data or None,
                             needed_by=form.needed_by.data, delivery_location=form.delivery_location.data or None,
                             justification=form.justification.data, requested_by_id=current_user.id,
                             **{owner.fk: owner.id})
        db.session.add(pr)
        db.session.flush()
        audit.record("procurement.request_created", f"Purchase request {pr.code} created", entity=pr)
        db.session.commit()
        flash(f"{pr.code} created. Add the items, then submit it for approval.", "success")
        return _back(pr, "#items")
    return render_template("procurement/request_form.html", form=form, owner=owner, owner_value=owner_key(owner))


@bp.route("/<int:rid>")
def request_detail(rid):
    pr = _load(rid)
    owner = pr.owner
    item_form, quote_form, select_form = ItemForm(prefix="i"), QuotationForm(prefix="q"), SelectionForm(prefix="s")
    quote_form.supplier_id.choices = [(0, "— Choose —")] + [(s.id, s.name) for s in Supplier.query.filter_by(
        status="active").order_by(Supplier.name)]
    quote_form.received_on.data = date.today()
    select_form.quotation_id.choices = [(0, "— Choose —")] + [
        (q.id, f"{q.supplier.name} — {owner.currency} {q.total_amount:,.2f}") for q in pr.quotations]
    if pr.selected_quotation_id:
        select_form.quotation_id.data = pr.selected_quotation_id
        select_form.selection_reason.data = pr.selection_reason
        select_form.evaluation_report.data = pr.evaluation_report
    orders = PurchaseOrder.query.filter_by(request_id=pr.id).order_by(PurchaseOrder.id).all()
    lowest = min((q.total_amount for q in pr.quotations), default=None)
    return render_template(
        "procurement/request.html", pr=pr, owner=owner, item_form=item_form, quote_form=quote_form,
        select_form=select_form, note_form=ReviewNoteForm(), order_form=OrderForm(order_date=date.today()),
        orders=orders, lowest=lowest, today=date.today(), line=line_figures(pr.budget_line),
        method_now=method_for(pr.estimated_total), methods=PurchaseRequest.METHODS,
        can_edit=pr.status == "draft" and pr.requested_by_id == current_user.id and not read_only(),
        can_approve=pr.status == "submitted" and can_approve_request(pr), can_process=can_process(),
        live_orders=[o for o in orders if o.status != "cancelled"])


@bp.route("/<int:rid>/items", methods=["POST"])
def add_item(rid):
    pr = _load(rid)
    if pr.status != "draft" or pr.requested_by_id != current_user.id or read_only():
        abort(403)
    form = ItemForm(prefix="i")
    if form.validate_on_submit():
        if form.is_asset.data and not form.asset_category.data:
            flash("Choose the asset category.", "danger")
            return _back(pr, "#items")
        pr.items.append(PurchaseRequestItem(organization_id=g.tenant.id, description=form.description.data,
                                            quantity=form.quantity.data, unit=form.unit.data,
                                            unit_cost=form.unit_cost.data, is_asset=form.is_asset.data,
                                            asset_category=form.asset_category.data or None))
        db.session.commit()
    else:
        flash("Item not added: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
    return _back(pr, "#items")


@bp.route("/<int:rid>/items/<int:iid>/delete", methods=["POST"])
def delete_item(rid, iid):
    pr = _load(rid)
    if pr.status != "draft" or pr.requested_by_id != current_user.id or not ActionForm().validate_on_submit():
        abort(403)
    item = tenant_get_or_404(PurchaseRequestItem, iid)
    if item.request_id != pr.id:
        abort(404)
    pr.items.remove(item)
    db.session.commit()
    return _back(pr, "#items")


@bp.route("/<int:rid>/<any(submit, approve, reject, cancel, reopen):action>", methods=["POST"])
def request_action(rid, action):
    pr = _load(rid)
    form = ReviewNoteForm()
    if not form.validate_on_submit():
        abort(400)
    note = form.note.data or None
    owner = pr.owner
    if action == "submit":
        if pr.status != "draft" or pr.requested_by_id != current_user.id or read_only():
            abort(403)
        if not pr.items:
            flash("Add at least one item first.", "danger")
            return _back(pr)
        if owner.status not in LIVE_OWNER:
            flash(f"{owner.code} is {owner.status}; purchases are only possible for approved or active work.", "danger")
            return _back(pr)
        pr.status, pr.submitted_at, pr.method = "submitted", utcnow(), method_for(pr.estimated_total)
        approvers = [u for u in holders("procurement.approve", owner) if u != current_user.id]
        notify(approvers, "procurement", f"Purchase request to approve: {pr.code}",
               f"{pr.title} — {owner.currency} {pr.estimated_total:,.2f}", "procurement.request_detail", rid=pr.id)
        msg = "Submitted for approval."
    elif action in ("approve", "reject"):
        if pr.status != "submitted":
            abort(400)
        if not can_approve_request(pr):
            if pr.requested_by_id == current_user.id:
                flash("Someone other than the requester must approve this.", "danger")
                return _back(pr)
            abort(403)
        if action == "approve":
            avail = line_figures(pr.budget_line)["available"]
            if pr.estimated_total > avail:
                flash(f"Not enough left on the budget line ({owner.currency} {avail:,.2f} available). "
                      "Revise the budget or reduce the request.", "danger")
                return _back(pr)
        elif not note:
            flash("Say why the request is rejected.", "danger")
            return _back(pr)
        pr.status = "approved" if action == "approve" else "rejected"
        pr.approved_by_id, pr.approved_at, pr.decision_note = current_user.id, utcnow(), note
        notify([pr.requested_by_id], "procurement", f"Purchase request {pr.status}: {pr.code}", note,
               "procurement.request_detail", rid=pr.id)
        if action == "approve":
            notify([u for u in holders("procurement.manage") if u != current_user.id], "procurement",
                   f"Approved request ready for quotations: {pr.code}", pr.title, "procurement.request_detail",
                   rid=pr.id)
        msg = "Request approved." if action == "approve" else "Request rejected."
    elif action == "cancel":
        mine = pr.requested_by_id == current_user.id
        if read_only() or not (mine or can_process()) or pr.status not in ("draft", "submitted", "approved"):
            abort(403)
        if PurchaseOrder.query.filter(PurchaseOrder.request_id == pr.id, PurchaseOrder.status != "cancelled").count():
            flash("Cancel its purchase order first.", "danger")
            return _back(pr)
        pr.status, pr.decision_note = "cancelled", note
        msg = "Request cancelled."
    else:  # reopen a rejected request as a draft
        if pr.status != "rejected" or pr.requested_by_id != current_user.id or read_only():
            abort(403)
        pr.status, pr.method = "draft", None
        msg = "Back to draft: change it and submit again."
    audit.record(f"procurement.request_{action}", f"{pr.code}: {pr.status}", entity=pr)
    db.session.commit()
    flash(msg, "success")
    return _back(pr)


# --- quotations and selection ------------------------------------------------------------------

@bp.route("/<int:rid>/quotations", methods=["POST"])
def add_quotation(rid):
    pr = _load(rid)
    if not can_process() or pr.status != "approved":
        abort(403)
    form = QuotationForm(prefix="q")
    form.supplier_id.choices = [(s.id, s.name) for s in Supplier.query.filter_by(status="active")]
    if form.validate_on_submit():
        if any(q.supplier_id == form.supplier_id.data for q in pr.quotations):
            flash("This supplier's quotation is already recorded.", "danger")
        else:
            pr.quotations.append(Quotation(organization_id=g.tenant.id, supplier_id=form.supplier_id.data,
                                           reference=form.reference.data or None, received_on=form.received_on.data,
                                           total_amount=form.total_amount.data, delivery_days=form.delivery_days.data,
                                           valid_until=form.valid_until.data, notes=form.notes.data or None,
                                           recorded_by_id=current_user.id))
            audit.record("procurement.quotation", f"{pr.code}: quotation recorded", entity=pr)
            db.session.commit()
            flash("Quotation recorded.", "success")
    else:
        flash("Quotation not saved: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
    return _back(pr, "#quotations")


@bp.route("/<int:rid>/quotations/<int:qid>/delete", methods=["POST"])
def delete_quotation(rid, qid):
    pr = _load(rid)
    if not can_process() or pr.status != "approved" or not ActionForm().validate_on_submit():
        abort(403)
    q = tenant_get_or_404(Quotation, qid)
    if q.request_id != pr.id:
        abort(404)
    if pr.selected_quotation_id == q.id:
        pr.selected_quotation_id = None
    db.session.delete(q)
    db.session.commit()
    return _back(pr, "#quotations")


@bp.route("/<int:rid>/select", methods=["POST"])
def select_quotation(rid):
    pr = _load(rid)
    if not can_process() or pr.status != "approved":
        abort(403)
    form = SelectionForm(prefix="s")
    form.quotation_id.choices = [(q.id, "") for q in pr.quotations]
    if not form.validate_on_submit():
        flash("Choose a quotation.", "danger")
        return _back(pr, "#quotations")
    q = next(q for q in pr.quotations if q.id == form.quotation_id.data)
    lowest = min(x.total_amount for x in pr.quotations)
    problems = []
    if len(pr.quotations) < pr.quotes_needed:
        problems.append(f"{PurchaseRequest.METHODS[pr.method]} are required: record {pr.quotes_needed} quotations "
                        f"(you have {len(pr.quotations)}).")
    if q.total_amount > lowest and not form.selection_reason.data:
        problems.append("This is not the lowest quotation: explain why it is the best value.")
    if pr.method == "tender" and not form.evaluation_report.data:
        problems.append("A tender needs the evaluation committee's report.")
    if problems:
        for p in problems:
            flash(p, "danger")
        return _back(pr, "#quotations")
    pr.selected_quotation_id, pr.selection_reason = q.id, form.selection_reason.data or None
    pr.evaluation_report = form.evaluation_report.data or None
    audit.record("procurement.selected", f"{pr.code}: {q.supplier.name} selected ({q.total_amount})", entity=pr)
    db.session.commit()
    flash(f"{q.supplier.name} selected. You can now prepare the purchase order.", "success")
    return _back(pr, "#order")


# ====================================================================================
# Purchase orders
# ====================================================================================

@bp.route("/<int:rid>/order", methods=["POST"])
def create_order(rid):
    pr = _load(rid)
    if not can_process() or pr.status != "approved" or not pr.selected_quotation_id:
        abort(403)
    if PurchaseOrder.query.filter(PurchaseOrder.request_id == pr.id, PurchaseOrder.status != "cancelled").count():
        flash("This request already has a purchase order.", "danger")
        return _back(pr, "#order")
    form = OrderForm()
    if not form.validate_on_submit():
        flash("Check the dates: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
        return _back(pr, "#order")
    q = pr.selected_quotation
    lines, total = [], Decimal(0)
    for item in pr.items:
        raw = request.form.get(f"price_{item.id}", "")
        try:
            price = Decimal(raw.replace(",", "")).quantize(CENT, ROUND_HALF_UP)
            if price < 0:
                raise InvalidOperation
        except (InvalidOperation, AttributeError):
            flash(f"Enter the agreed unit price for “{item.description}”.", "danger")
            return _back(pr, "#order")
        lines.append((item, price))
        total += (Decimal(item.quantity) * price).quantize(CENT, ROUND_HALF_UP)
    if total > q.total_amount:
        flash(f"The order ({total:,.2f}) cannot be more than the chosen quotation ({q.total_amount:,.2f}).", "danger")
        return _back(pr, "#order")
    po = PurchaseOrder(organization_id=g.tenant.id, code=next_reference("PO"), request_id=pr.id,
                       supplier_id=q.supplier_id, quotation_id=q.id, order_date=form.order_date.data,
                       delivery_date=form.delivery_date.data, terms=form.terms.data or None,
                       created_by_id=current_user.id)
    for item, price in lines:
        po.items.append(PurchaseOrderItem(organization_id=g.tenant.id, description=item.description,
                                          quantity=item.quantity, unit=item.unit, unit_price=price,
                                          is_asset=item.is_asset, asset_category=item.asset_category))
    db.session.add(po)
    db.session.flush()
    notify([u for u in holders("finance.approve", pr.owner) if u != current_user.id], "procurement",
           f"Purchase order to approve: {po.code}", f"{q.supplier.name} — {pr.owner.currency} {total:,.2f}",
           "procurement.order", oid=po.id)
    audit.record("procurement.order_created", f"{po.code} prepared for {pr.code}", entity=po)
    db.session.commit()
    flash(f"{po.code} prepared. It needs approval by finance, which commits the money.", "success")
    return redirect(url_for("procurement.order", oid=po.id))


def _load_order(oid):
    po = tenant_get_or_404(PurchaseOrder, oid)
    if not can_see_request(po.request):
        abort(404)
    return po


@bp.route("/orders/<int:oid>")
def order(oid):
    po = _load_order(oid)
    pr, owner = po.request, po.request.owner
    payments = Expenditure.query.filter_by(purchase_order_id=po.id, kind="expenditure").order_by(Expenditure.id).all()
    pay_form = PaymentForm()
    pay_form.paid_on.data = date.today()
    can_approve = (not read_only() and po.status == "draft" and can_do("finance.approve", owner)
                   and po.created_by_id != current_user.id)
    return render_template("procurement/order.html", po=po, pr=pr, owner=owner, fig=po_figures(po), payments=payments,
                           receipt_form=ReceiptForm(received_on=date.today()), pay_form=pay_form,
                           cancel_form=CancelForm(), note_form=ReviewNoteForm(), can_approve=can_approve,
                           can_receive=_can_receive(po), can_pay=not read_only() and can_do("finance.record", owner),
                           can_process=can_process(), today=date.today())


def _can_receive(po):
    """The procurement office, or the person who asked for the goods, records what arrived."""
    return (not read_only() and po.status in ("approved", "partially_received")
            and (can_process() or po.request.requested_by_id == current_user.id))


@bp.route("/orders/<int:oid>/<any(approve, cancel):action>", methods=["POST"])
def order_action(oid, action):
    po = _load_order(oid)
    pr, owner = po.request, po.request.owner
    back = redirect(url_for("procurement.order", oid=po.id))
    if action == "approve":
        if not ReviewNoteForm().validate_on_submit() or po.status != "draft":
            abort(400)
        if read_only() or not can_do("finance.approve", owner):
            abort(403)
        if po.created_by_id == current_user.id:
            flash("Someone other than the person who prepared the order must approve it.", "danger")
            return back
        avail = line_figures(pr.budget_line)["available"]
        if po.total > avail:
            flash(f"Not enough left on the budget line ({owner.currency} {avail:,.2f}). Revise the budget first.",
                  "danger")
            return back
        com = Expenditure(organization_id=g.tenant.id, budget_line_id=pr.budget_line_id, activity_id=pr.activity_id,
                          kind="commitment", spent_on=date.today(), description=f"{po.code} — {po.supplier.name}",
                          payee=po.supplier.name, reference=po.code, amount=po.total, status="approved",
                          recorded_by_id=po.created_by_id, approved_by_id=current_user.id, approved_at=utcnow(),
                          purchase_order_id=po.id, **{owner.fk: owner.id})
        db.session.add(com)
        db.session.flush()
        po.status, po.approved_by_id, po.approved_at, po.commitment_id = "approved", current_user.id, utcnow(), com.id
        pr.status = "ordered"
        notify({po.created_by_id, pr.requested_by_id} - {current_user.id, None}, "procurement",
               f"{po.code} approved — send it to {po.supplier.name}", None, "procurement.order", oid=po.id)
        msg = f"Approved. {owner.currency} {po.total:,.2f} is now committed on the budget line."
    else:
        form = CancelForm()
        if not form.validate_on_submit():
            flash("Give a reason for cancelling.", "danger")
            return back
        if not can_process() or po.status not in ("draft", "approved") or po.receipts or \
                Expenditure.query.filter(Expenditure.purchase_order_id == po.id, Expenditure.kind == "expenditure",
                                         Expenditure.status.in_(("pending", "approved"))).count():
            flash("Only an order with nothing received or paid can be cancelled.", "danger")
            return back
        if po.commitment is not None and po.commitment.status == "approved":
            po.commitment.status = "cancelled"
            po.commitment.decision_note = f"Released: {po.code} cancelled"
        po.status, po.cancel_reason = "cancelled", form.reason.data
        pr.status = "approved"
        msg = "Order cancelled and the committed money released."
    audit.record(f"procurement.order_{action}", f"{po.code}: {po.status}", entity=po)
    db.session.commit()
    flash(msg, "success")
    return back


@bp.route("/orders/<int:oid>/receive", methods=["POST"])
def receive(oid):
    po = _load_order(oid)
    if not _can_receive(po):
        abort(403)
    form = ReceiptForm()
    back = redirect(url_for("procurement.order", oid=po.id) + "#receive")
    if not form.validate_on_submit():
        flash("Enter the date received.", "danger")
        return back
    if form.received_on.data > date.today() or form.received_on.data < po.order_date:
        flash("The date must be between the order date and today.", "danger")
        return back
    lines = []
    for item in po.items:
        raw = (request.form.get(f"qty_{item.id}") or "0").strip()
        try:
            qty = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            flash(f"Enter a number for “{item.description}”.", "danger")
            return back
        if qty < 0 or qty > item.outstanding:
            flash(f"“{item.description}”: between 0 and {item.outstanding:g} can still be received.", "danger")
            return back
        if qty and item.is_asset and qty != qty.to_integral_value():
            flash(f"“{item.description}” is an asset: receive whole units.", "danger")
            return back
        if qty:
            lines.append((item, qty, request.form.get(f"cond_{item.id}") or "good"))
    if not lines:
        flash("Enter the quantity received for at least one item.", "danger")
        return back
    grn = GoodsReceipt(organization_id=g.tenant.id, code=next_reference("GRN"), order_id=po.id,
                       received_on=form.received_on.data, received_by_id=current_user.id,
                       delivery_note=form.delivery_note.data or None, notes=form.notes.data or None, lines=[])
    db.session.add(grn)
    owner, made = po.request.owner, 0
    for item, qty, cond in lines:
        item.received_qty = Decimal(item.received_qty or 0) + qty
        grn.lines = grn.lines + [{"item_id": item.id, "description": item.description, "quantity": float(qty),
                                  "condition": cond}]
        if item.is_asset:
            life = Asset.CATEGORIES.get(item.asset_category or "Other", 5)
            for _ in range(int(qty)):
                a = Asset(organization_id=g.tenant.id, code=next_reference("AST"), name=item.description[:200],
                          category=item.asset_category or "Other", purchase_date=form.received_on.data,
                          cost=item.unit_price, currency=owner.currency, useful_life_years=life,
                          supplier_id=po.supplier_id, order_id=po.id, status="in_store",
                          condition="new" if cond == "good" else cond,
                          donor_id=getattr(owner, "donor_id", None), department_id=owner.department_id,
                          created_by_id=current_user.id, **{owner.fk: owner.id})
                db.session.add(a)
                db.session.flush()
                db.session.add(AssetEvent(organization_id=g.tenant.id, asset_id=a.id, kind="received",
                                          happened_on=form.received_on.data, actor_id=current_user.id,
                                          note=f"Received on {po.code}"))
                made += 1
    po.status = "received" if po.fully_received else "partially_received"
    db.session.flush()
    notify([u for u in holders("finance.record", owner) if u != current_user.id], "procurement",
           f"Goods received on {po.code}: ready for payment", None, "procurement.order", oid=po.id)
    audit.record("procurement.received", f"{grn.code} for {po.code}" + (f"; {made} asset(s) registered" if made else ""),
                 entity=po)
    db.session.commit()
    flash(f"{grn.code} recorded." + (f" {made} asset(s) added to the register — give them tags and custodians."
                                     if made else ""), "success")
    return back


@bp.route("/orders/<int:oid>/pay", methods=["POST"])
def pay(oid):
    """Record a payment (pending). A second person approves it on the finance page; that releases the commitment."""
    po = _load_order(oid)
    owner = po.request.owner
    if read_only() or not can_do("finance.record", owner) or po.status not in ("partially_received", "received"):
        abort(403)
    form = PaymentForm()
    back = redirect(url_for("procurement.order", oid=po.id) + "#payments")
    if not form.validate_on_submit():
        flash("Check the payment: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
        return back
    fig = po_figures(po)
    if form.amount.data > fig["payable"]:
        flash(f"Only {owner.currency} {fig['payable']:,.2f} can be paid: payments cannot exceed the value of goods "
              "received (less what is already paid or waiting for approval).", "danger")
        return back
    e = Expenditure(organization_id=g.tenant.id, budget_line_id=po.request.budget_line_id,
                    activity_id=po.request.activity_id, kind="expenditure", spent_on=form.paid_on.data,
                    description=f"Payment {po.code} — {po.supplier.name}", payee=po.supplier.name,
                    reference=form.reference.data, amount=form.amount.data, status="pending",
                    recorded_by_id=current_user.id, purchase_order_id=po.id, **{owner.fk: owner.id})
    db.session.add(e)
    db.session.flush()
    notify([u for u in holders("finance.approve", owner) if u != current_user.id], "finance",
           f"Payment to approve: {po.code}", f"{po.supplier.name} — {owner.currency} {e.amount:,.2f}",
           f"{owner.perm}.finance", pid=owner.id, status="pending")
    audit.record("procurement.payment_recorded", f"Payment {e.amount} on {po.code}", entity=po)
    db.session.commit()
    flash("Payment recorded and sent for approval.", "success")
    return back


def after_payment_approved(e):
    """Called when a payment on an order is approved: release that much of the commitment; close the order when done."""
    po = e.purchase_order
    com = po.commitment if po else None
    if com is not None and com.status == "approved":
        release = min(Decimal(e.amount), Decimal(com.amount))
        com.amount = Decimal(com.amount) - release
        audit.record("finance.commitment_released", f"{po.code}: {release} of the commitment released by payment",
                     entity=com)
    from app.procurement_logic import po_paid
    db.session.flush()
    if po is not None and po.fully_received and po_paid(po) >= po.total:
        po.status = "closed"
        if com is not None and Decimal(com.amount) > 0:
            com.status = "cancelled"
            com.decision_note = "Released: order closed"
        po.request.status = "completed"


def commitment_release(e):
    """How much of an order's commitment a pending payment would release (for the funds check)."""
    if e.kind != "expenditure" or not e.purchase_order_id:
        return Decimal(0)
    com = e.purchase_order.commitment if e.purchase_order else None
    if com is None or com.status != "approved":
        return Decimal(0)
    return min(Decimal(e.amount), Decimal(com.amount))


# ====================================================================================
# Suppliers
# ====================================================================================

@bp.route("/suppliers/")
@require_permission("procurement.view")
def suppliers():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or "active"
    stmt = select(Supplier).where(Supplier.organization_id == g.tenant.id)
    if status in Supplier.STATUSES:
        stmt = stmt.where(Supplier.status == status)
    if q:
        stmt = stmt.where(or_(Supplier.name.ilike(f"%{q}%"), Supplier.category.ilike(f"%{q}%"),
                              Supplier.code.ilike(f"%{q}%")))
    page = db.paginate(stmt.order_by(Supplier.name), page=page_arg(), per_page=40, error_out=False)
    return render_template("procurement/suppliers.html", page=page, q=q, status=status, can_process=can_process())


@bp.route("/suppliers/new", methods=["GET", "POST"])
@bp.route("/suppliers/<int:sid>/edit", methods=["GET", "POST"])
def supplier_edit(sid=None):
    if not can_process():
        abort(403)
    s = tenant_get_or_404(Supplier, sid) if sid else None
    form = SupplierForm(obj=s)
    if request.method == "GET" and s:
        form.bank_account.data = decrypt_text(s.bank_account_enc)
    if form.validate_on_submit():
        dup = Supplier.query.filter(Supplier.name.ilike(form.name.data), Supplier.id != (s.id if s else 0)).first()
        if dup:
            form.name.errors.append(f"{dup.code} already has this name.")
        else:
            if s is None:
                s = Supplier(organization_id=g.tenant.id, code=next_reference("SUP"), created_by_id=current_user.id)
                db.session.add(s)
            s.name, s.category = form.name.data, form.category.data
            for f in ("contact_person", "phone", "email", "address", "tax_id", "bank_name", "notes"):
                setattr(s, f, getattr(form, f).data or None)
            s.bank_account_enc = encrypt_text(form.bank_account.data)
            db.session.flush()
            audit.record("procurement.supplier", f"Supplier {s.code} saved", entity=s)
            db.session.commit()
            flash("Supplier saved.", "success")
            return redirect(url_for("procurement.supplier", sid=s.id))
    return render_template("procurement/supplier_form.html", form=form, s=s)


@bp.route("/suppliers/<int:sid>", methods=["GET", "POST"])
@require_permission("procurement.view")
def supplier(sid):
    s = tenant_get_or_404(Supplier, sid)
    form = SupplierStatusForm(obj=s)
    if request.method == "POST":
        if not can_process():
            abort(403)
        if form.validate_on_submit():
            if form.status.data != "active" and not form.status_reason.data:
                flash("Give a reason for suspending or blacklisting.", "danger")
            else:
                s.status, s.status_reason, s.rating = form.status.data, form.status_reason.data or None, \
                    form.rating.data or None
                audit.record("procurement.supplier_status", f"Supplier {s.code}: {s.status}", entity=s)
                db.session.commit()
                flash("Saved.", "success")
        return redirect(url_for("procurement.supplier", sid=s.id))
    orders = PurchaseOrder.query.filter_by(supplier_id=s.id).order_by(PurchaseOrder.id.desc()).limit(30).all()
    orders = [o for o in orders if can_see_request(o.request)]
    return render_template("procurement/supplier.html", s=s, form=form, orders=orders, can_process=can_process(),
                           bank_account=decrypt_text(s.bank_account_enc) if (can_process() or can("finance.record"))
                           else None)


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if not can_process() or scope_of("procurement.manage") != ORG:
        abort(403)
    org = g.tenant
    form = ThresholdForm(obj=org)
    if form.validate_on_submit():
        org.proc_quotes_threshold, org.proc_tender_threshold = form.proc_quotes_threshold.data, \
            form.proc_tender_threshold.data
        audit.record("procurement.thresholds", f"Thresholds: 3 quotes from {org.proc_quotes_threshold}, tender from "
                     f"{org.proc_tender_threshold}", entity=org)
        db.session.commit()
        flash("Thresholds saved. They apply to requests submitted from now on.", "success")
        return redirect(url_for("procurement.settings"))
    return render_template("procurement/settings.html", form=form, org=org)
