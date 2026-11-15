"""Asset register: tagging, custody, transfers, maintenance, verification, depreciation and disposal."""
import io
from datetime import date, timedelta
from decimal import Decimal

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import or_

from app import audit
from app.blueprints.beneficiaries import location_choices, owner_choices, owner_key, parse_owner
from app.blueprints.people import department_choices
from app.blueprints.tenant import is_member, member_choices, page_arg, workspace_blueprint
from app.extensions import db
from app.forms import ActionForm, CURRENCIES
from app.forms_procurement import AssetEventForm, AssetForm, AssignForm, DisposalForm, TransferForm
from app.forms_programmes import ReviewNoteForm
from app.models import Asset, AssetEvent, Department, Donor, Location
from app.notify import next_reference, notify
from app.procurement_logic import can_manage_asset, can_see_asset, read_only, visible_assets_stmt
from app.programme_logic import holders, visible_owner_stmt
from app.rbac import can
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("assets", __name__, "/assets")
VERIFY_EVERY_DAYS = 365


def _owners():
    return [o for k in ("programme", "project") for o in db.session.execute(visible_owner_stmt(k).order_by("code")).scalars()
            if o.status not in ("closed", "cancelled")]


def _load(aid):
    a = tenant_get_or_404(Asset, aid)
    if not can("assets.view") or not can_see_asset(a):
        abort(404)
    return a


def _event(a, kind, on, note=None, **kw):
    a.history.append(AssetEvent(organization_id=g.tenant.id, kind=kind, happened_on=on, note=note,
                                actor_id=current_user.id, **kw))


@bp.route("/")
def index():
    if not can("assets.view"):
        abort(403)
    f = {k: request.args.get(k) or "" for k in ("q", "status", "category", "owner", "view")}
    stmt = visible_assets_stmt()
    if f["view"] == "mine":
        stmt = stmt.where(Asset.custodian_id == current_user.id)
    elif f["view"] == "verify":
        stmt = stmt.where(Asset.status != "disposed", or_(Asset.last_verified_on.is_(None),
                                                          Asset.last_verified_on < date.today() - timedelta(days=VERIFY_EVERY_DAYS)))
    elif f["view"] == "disposal":
        stmt = stmt.where(Asset.disposal_status == "requested")
    if f["status"] in Asset.STATUSES:
        stmt = stmt.where(Asset.status == f["status"])
    elif not f["status"] and f["view"] != "disposal":
        stmt = stmt.where(Asset.status != "disposed")
    if f["category"] in Asset.CATEGORIES:
        stmt = stmt.where(Asset.category == f["category"])
    if f["owner"]:
        o = parse_owner(f["owner"])
        stmt = stmt.where(getattr(Asset, o.fk) == o.id)
    if f["q"]:
        like = f"%{f['q']}%"
        stmt = stmt.where(or_(Asset.name.ilike(like), Asset.code.ilike(like), Asset.serial_number.ilike(like),
                              Asset.make_model.ilike(like)))
    rows = db.session.execute(stmt.order_by(Asset.code)).scalars().all()
    totals = {}
    for a in rows:
        t = totals.setdefault(a.currency, {"cost": Decimal(0), "book": Decimal(0)})
        if a.status != "disposed":
            t["cost"] += Decimal(a.cost or 0)
            t["book"] += a.book_value()
    page = db.paginate(stmt.order_by(Asset.code), page=page_arg(), per_page=40, error_out=False)
    return render_template("assets/index.html", page=page, f=f, totals=totals, categories=Asset.CATEGORIES,
                           owner_opts=owner_choices([o for k in ("programme", "project") for o in db.session.execute(
                               visible_owner_stmt(k).order_by("code")).scalars()]),
                           can_manage=can_manage_asset(), today=date.today())


def _setup(form):
    form.currency.choices = CURRENCIES
    form.owner.choices = owner_choices(_owners(), "— Organization (not a programme or project) —")
    form.donor_id.choices = [(0, "— None —")] + [(d.id, d.name) for d in Donor.query.filter_by(
        organization_id=g.tenant.id).order_by(Donor.name)]
    form.location_id.choices = location_choices()
    form.department_id.choices = department_choices()


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:aid>/edit", methods=["GET", "POST"])
def edit(aid=None):
    a = _load(aid) if aid else None
    if not can_manage_asset(a):
        abort(403)
    form = AssetForm(obj=a)
    _setup(form)
    if a and a.owner and owner_key(a.owner) not in dict(form.owner.choices):
        form.owner.choices.append((owner_key(a.owner), f"{a.owner.code} — {a.owner.title[:70]}"))
    if request.method == "GET":
        form.owner.data = owner_key(a.owner) if a and a.owner else ""
        if not a:
            form.currency.data = g.tenant.currency
    if form.validate_on_submit():
        owner = parse_owner(form.owner.data) if form.owner.data else None
        if owner is not None and owner_key(owner) not in dict(form.owner.choices):
            abort(403)
        for model, fid in ((Donor, form.donor_id.data), (Location, form.location_id.data),
                           (Department, form.department_id.data)):
            if fid:
                tenant_get_or_404(model, fid)
        if form.serial_number.data:
            dup = Asset.query.filter(Asset.serial_number == form.serial_number.data,
                                     Asset.id != (a.id if a else 0)).first()
            if dup:
                form.serial_number.errors.append(f"{dup.code} already has this serial number.")
        if (form.residual_value.data or 0) > (form.cost.data or 0):
            form.residual_value.errors.append("Cannot be more than the cost.")
        if not form.errors:
            creating = a is None
            if creating:
                a = Asset(organization_id=g.tenant.id, code=next_reference("AST"), created_by_id=current_user.id,
                          status="in_store")
                db.session.add(a)
            for fld in ("name", "category", "make_model", "serial_number", "description", "purchase_date",
                        "currency", "warranty_until", "insured", "notes", "condition"):
                v = getattr(form, fld).data
                setattr(a, fld, v if v not in ("",) else None)
            a.cost, a.residual_value = form.cost.data or 0, form.residual_value.data or 0
            a.useful_life_years = form.useful_life_years.data or Asset.CATEGORIES.get(a.category, 5)
            a.programme_id = owner.id if owner and owner.kind == "programme" else None
            a.project_id = owner.id if owner and owner.kind == "project" else None
            a.donor_id, a.location_id = form.donor_id.data or None, form.location_id.data or None
            a.department_id = form.department_id.data or None
            db.session.flush()
            if creating:
                _event(a, "registered", date.today())
            audit.record("asset.saved", f"Asset {a.code} {'registered' if creating else 'updated'}", entity=a)
            db.session.commit()
            flash(f"Saved as {a.code}." if creating else "Saved.", "success")
            return redirect(url_for("assets.detail", aid=a.id))
    return render_template("assets/form.html", form=form, a=a)


@bp.route("/<int:aid>")
def detail(aid):
    a = _load(aid)
    assign = AssignForm(prefix="a")
    assign.to_user_id.choices = [(0, "— Choose —")] + member_choices()
    assign.happened_on.data = date.today()
    transfer = TransferForm(prefix="t")
    transfer.owner.choices = owner_choices(_owners(), "— Organization (not a programme or project) —")
    transfer.location_id.choices = location_choices()
    transfer.department_id.choices = department_choices()
    transfer.happened_on.data = date.today()
    transfer.owner.data = owner_key(a.owner) if a.owner else ""
    transfer.location_id.data, transfer.department_id.data = a.location_id, a.department_id
    ev = AssetEventForm(prefix="e")
    ev.happened_on.data = date.today()
    return render_template("assets/detail.html", a=a, assign_form=assign, transfer_form=transfer, event_form=ev,
                           disposal_form=DisposalForm(prefix="d"), note_form=ReviewNoteForm(), action_form=ActionForm(),
                           can_manage=can_manage_asset(a),
                           can_decide=(not read_only() and can("assets.approve") and a.disposal_status == "requested"
                                       and a.disposal_requested_by_id != current_user.id),
                           kinds=AssetEvent.KINDS, methods=Asset.DISPOSAL_METHODS, today=date.today(),
                           verify_due=a.status != "disposed" and (a.last_verified_on is None or
                                                                  a.last_verified_on < date.today() - timedelta(days=VERIFY_EVERY_DAYS)))


@bp.route("/<int:aid>/<any(assign, return, transfer, maintenance, repair, verify, lost, dispose, decide):action>",
          methods=["POST"])
def act(aid, action):
    a = _load(aid)
    back = redirect(url_for("assets.detail", aid=a.id))
    if action == "decide":
        return _decide(a)
    if not can_manage_asset(a):
        abort(403)
    if a.disposal_status == "requested" and action != "verify":
        flash("A disposal is waiting for approval; decide it first.", "warning")
        return back
    if action == "assign":
        form = AssignForm(prefix="a")
        form.to_user_id.choices = member_choices()
        if not form.validate_on_submit() or not is_member(form.to_user_id.data):
            flash("Choose a person and a date.", "danger")
            return back
        if a.status in ("lost",):
            abort(400)
        prev = a.custodian_id
        a.custodian_id, a.status = form.to_user_id.data, "in_use"
        _event(a, "assigned", form.happened_on.data, form.note.data or None, to_user_id=form.to_user_id.data)
        notify([a.custodian_id], "asset", f"Asset in your care: {a.code} {a.name}",
               "Please look after it and report any damage or loss.", "assets.detail", aid=a.id)
        if prev and prev != a.custodian_id:
            notify([prev], "asset", f"{a.code} {a.name} was reassigned", None, "assets.detail", aid=a.id)
    elif action == "return":
        form = AssetEventForm(prefix="e")
        if not form.validate_on_submit() or a.custodian_id is None:
            abort(400)
        if form.condition.data:
            a.condition = form.condition.data
        _event(a, "returned", form.happened_on.data, form.note.data or None, to_user_id=a.custodian_id)
        a.custodian_id, a.status = None, "in_store"
    elif action == "transfer":
        form = TransferForm(prefix="t")
        form.owner.choices = owner_choices(_owners(), "")
        form.location_id.choices, form.department_id.choices = location_choices(), department_choices()
        if not form.validate_on_submit():
            flash("Give the date and the reason for the transfer.", "danger")
            return back
        owner = parse_owner(form.owner.data) if form.owner.data else None
        if owner is not None and owner_key(owner) not in dict(form.owner.choices):
            abort(403)
        if form.location_id.data:
            tenant_get_or_404(Location, form.location_id.data)
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        before = a.owner.code if a.owner else "Organization"
        a.programme_id = owner.id if owner and owner.kind == "programme" else None
        a.project_id = owner.id if owner and owner.kind == "project" else None
        a.location_id, a.department_id = form.location_id.data or None, form.department_id.data or None
        after = owner.code if owner else "Organization"
        _event(a, "transferred", form.happened_on.data, f"{before} → {after}. {form.note.data}")
    elif action in ("maintenance", "repair", "verify", "lost"):
        form = AssetEventForm(prefix="e")
        if not form.validate_on_submit():
            flash("Check the date.", "danger")
            return back
        if action == "verify" and not form.note.data:
            form.note.data = "Seen and checked"
        if action in ("repair", "lost") and not form.note.data:
            flash("Describe what happened.", "danger")
            return back
        if form.condition.data:
            a.condition = form.condition.data
        if action == "verify":
            a.last_verified_on, a.last_verified_by_id = form.happened_on.data, current_user.id
        elif action == "repair":
            a.status = "under_repair" if a.status != "disposed" else a.status
        elif action == "lost":
            a.status = "lost"
            notify([u for u in holders("assets.approve") if u != current_user.id], "asset",
                   f"Asset reported lost: {a.code} {a.name}", form.note.data, "assets.detail", aid=a.id)
        if action == "maintenance" and a.status == "under_repair":
            a.status = "in_use" if a.custodian_id else "in_store"
        _event(a, {"verify": "verified"}.get(action, action), form.happened_on.data, form.note.data or None,
               cost=form.cost.data,
               next_due=form.next_due.data if action == "maintenance" else None)
    elif action == "dispose":
        form = DisposalForm(prefix="d")
        if not form.validate_on_submit():
            flash("Give the method and the reason.", "danger")
            return back
        if a.donor_id and form.disposal_method.data not in ("return_donor", "donation", "write_off") and \
                not request.form.get("donor_ok"):
            flash("This asset was funded by a donor. Confirm the donor agreed to this disposal.", "danger")
            return back
        a.disposal_status, a.disposal_method = "requested", form.disposal_method.data
        a.disposal_reason, a.disposal_value = form.disposal_reason.data, form.disposal_value.data
        a.disposal_requested_by_id = current_user.id
        _event(a, "disposal_requested", date.today(), f"{Asset.DISPOSAL_METHODS[a.disposal_method]}: {a.disposal_reason}")
        notify([u for u in holders("assets.approve") if u != current_user.id], "asset",
               f"Asset disposal to approve: {a.code} {a.name}", a.disposal_reason, "assets.detail", aid=a.id)
    audit.record(f"asset.{action}", f"Asset {a.code}: {action}", entity=a)
    db.session.commit()
    flash("Saved.", "success")
    return back


def _decide(a):
    form = ReviewNoteForm()
    back = redirect(url_for("assets.detail", aid=a.id))
    if read_only() or not can("assets.approve") or a.disposal_status != "requested" or not form.validate_on_submit():
        abort(403)
    if a.disposal_requested_by_id == current_user.id:
        flash("Someone other than the person who asked must approve the disposal.", "danger")
        return back
    decision = request.form.get("decision")
    if decision == "approve":
        a.disposal_status, a.status, a.disposed_on = "approved", "disposed", date.today()
        a.disposal_approved_by_id, a.custodian_id = current_user.id, None
        _event(a, "disposal_approved", date.today(), form.note.data or None)
    elif decision == "reject":
        if not form.note.data:
            flash("Say why the disposal is refused.", "danger")
            return back
        a.disposal_status = "rejected"
        _event(a, "disposal_rejected", date.today(), form.note.data)
    else:
        abort(400)
    notify([a.disposal_requested_by_id], "asset", f"Disposal of {a.code} {a.disposal_status}", form.note.data,
           "assets.detail", aid=a.id)
    audit.record(f"asset.disposal_{decision}", f"Asset {a.code}: disposal {a.disposal_status}", entity=a)
    db.session.commit()
    flash("Decision recorded.", "success")
    return back


@bp.route("/export.xlsx")
def export():
    import openpyxl
    from openpyxl.styles import Font
    if not can("assets.view"):
        abort(403)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Assets"
    ws.append(["Tag", "Asset", "Category", "Make / model", "Serial", "Status", "Condition", "Custodian", "Location",
               "Funded by", "Donor", "Purchase date", "Currency", "Cost", "Book value today", "Last verified"])
    for c in ws[1]:
        c.font = Font(bold=True)
    for a in db.session.execute(visible_assets_stmt().order_by(Asset.code)).scalars():
        ws.append([a.code, a.name, a.category, a.make_model or "", a.serial_number or "", a.status.replace("_", " "),
                   a.condition, a.custodian.full_name if a.custodian else "", a.location.label if a.location else "",
                   a.owner.code if a.owner else "Organization", a.donor.name if a.donor else "",
                   a.purchase_date.isoformat() if a.purchase_date else "", a.currency, float(a.cost or 0),
                   float(a.book_value()), a.last_verified_on.isoformat() if a.last_verified_on else ""])
    for col in ("N", "O"):
        for cell in ws[col][1:]:
            cell.number_format = "#,##0.00"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    audit.record("asset.exported", "Asset register exported")
    db.session.commit()
    return send_file(buf, as_attachment=True, download_name=f"asset-register-{date.today()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
