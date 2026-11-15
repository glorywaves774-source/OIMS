"""Incoming and outgoing correspondence and internal memos."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from app import audit
from app.blueprints.people import department_choices
from app.blueprints.tenant import (in_scope, is_member, member_choices, my_department_id, page_arg, scoped,
                                   workspace_blueprint)
from app.extensions import db
from app.forms import ActionForm
from app.forms_office import CorrespondenceForm, NoteForm, RouteForm
from app.models import Correspondence, CorrespondenceAction, Department
from app.notify import next_reference, notify
from app.rbac import can, require_permission
from app.storage import UploadRejected
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("correspondence", __name__, "/correspondence")


def _handlers(item):
    return {item.assigned_to_id, item.created_by_id} - {None}


def can_view_correspondence(item):
    if can("correspondence.manage"):
        return True
    if current_user.id in _handlers(item):
        return True
    if item.confidential:
        return False
    return can("correspondence.view") and in_scope("correspondence.view", item.department_id,
                                                   owner_ids=tuple(_handlers(item)))


def _can_handle(item):
    return can("correspondence.manage") or item.assigned_to_id == current_user.id


def _log(item, action, note=None, to_user_id=None):
    db.session.add(CorrespondenceAction(organization_id=g.tenant.id, correspondence_id=item.id, action=action,
                                        actor_id=current_user.id, to_user_id=to_user_id, note=note))


@bp.route("/")
def index():
    if not (can("correspondence.view") or can("correspondence.create")):
        abort(403)
    kind = request.args.get("kind") or ""
    status = request.args.get("status") or ""
    q = (request.args.get("q") or "").strip()
    mine = request.args.get("mine") == "1"
    archived = request.args.get("archived") == "1"
    stmt = select(Correspondence).where(Correspondence.organization_id == g.tenant.id,
                                        Correspondence.archived.is_(archived))
    if not can("correspondence.manage"):
        handled = or_(Correspondence.assigned_to_id == current_user.id, Correspondence.created_by_id == current_user.id)
        if can("correspondence.view"):
            visible = scoped(select(Correspondence.id), "correspondence.view", dept_col=Correspondence.department_id,
                             own_cols=(Correspondence.assigned_to_id, Correspondence.created_by_id))
            stmt = stmt.where(or_(handled, Correspondence.id.in_(visible) & Correspondence.confidential.is_(False)))
        else:
            stmt = stmt.where(handled)
    if mine:
        stmt = stmt.where(Correspondence.assigned_to_id == current_user.id)
    if kind in Correspondence.KINDS:
        stmt = stmt.where(Correspondence.kind == kind)
    if status in Correspondence.STATUSES:
        stmt = stmt.where(Correspondence.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Correspondence.subject.ilike(like), Correspondence.reference_no.ilike(like),
                              Correspondence.party.ilike(like), Correspondence.external_reference.ilike(like)))
    page = db.paginate(stmt.order_by(Correspondence.created_at.desc()), page=page_arg(), per_page=25, error_out=False)
    return render_template("correspondence/index.html", page=page, kind=kind, status=status, q=q, mine=mine,
                           archived=archived, kinds=Correspondence.KINDS, statuses=Correspondence.STATUSES,
                           today=date.today())


def _setup(form):
    form.department_id.choices = department_choices()
    form.assigned_to_id.choices = member_choices("— Not assigned yet —")


@bp.route("/new", methods=["GET", "POST"])
@require_permission("correspondence.create")
def new():
    form = CorrespondenceForm()
    _setup(form)
    reply_to = None
    if request.values.get("reply_to"):
        reply_to = tenant_get_or_404(Correspondence, request.values.get("reply_to", type=int))
        if not can_view_correspondence(reply_to):
            abort(404)
    if request.method == "GET":
        form.kind.data = request.args.get("kind") if request.args.get("kind") in Correspondence.KINDS else "incoming"
        form.department_id.data = my_department_id()
        if reply_to:
            form.kind.data, form.subject.data, form.party.data = "outgoing", f"Re: {reply_to.subject}"[:300], reply_to.party
            form.department_id.data = reply_to.department_id
    if form.validate_on_submit():
        if form.assigned_to_id.data and not is_member(form.assigned_to_id.data):
            abort(400)
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        prefix = Correspondence.KINDS[form.kind.data][0]
        item = Correspondence(organization_id=g.tenant.id, created_by_id=current_user.id,
                              reference_no=next_reference(prefix), in_reply_to_id=reply_to.id if reply_to else None)
        for f in ("kind", "subject", "party", "external_reference", "letter_date", "received_date", "summary",
                  "priority", "confidential", "department_id", "assigned_to_id", "response_due"):
            setattr(item, f, getattr(form, f).data if getattr(form, f).data not in ("",) else None)
        item.confidential = bool(form.confidential.data)
        item.status = "assigned" if item.assigned_to_id else "registered"
        db.session.add(item)
        db.session.flush()
        _log(item, "registered", form.summary.data[:500] if form.summary.data else None)
        if form.file.data and getattr(form.file.data, "filename", ""):
            from app.blueprints.documents import create_attachment
            try:
                create_attachment("correspondence", item.id, form.file.data)
            except UploadRejected as exc:
                db.session.rollback()
                form.file.errors.append(str(exc))
                return render_template("correspondence/form.html", form=form, item=None, reply_to=reply_to)
        if item.assigned_to_id:
            _log(item, "assigned", None, item.assigned_to_id)
            notify([item.assigned_to_id], "correspondence", f"Assigned to you: {item.reference_no} {item.subject}",
                   f"Response due {item.response_due:%d %b %Y}" if item.response_due else None,
                   "correspondence.detail", item_id=item.id)
        audit.record("correspondence.registered", f"{item.reference_no} registered", entity=item)
        db.session.commit()
        flash(f"Registered as {item.reference_no}.", "success")
        return redirect(url_for("correspondence.detail", item_id=item.id))
    return render_template("correspondence/form.html", form=form, item=None, reply_to=reply_to)


@bp.route("/<int:item_id>")
def detail(item_id):
    item = tenant_get_or_404(Correspondence, item_id)
    if not can_view_correspondence(item):
        abort(404)
    from app.blueprints.documents import attachments_for
    route_form = RouteForm()
    route_form.to_user_id.choices = member_choices("— Choose —")
    replies = Correspondence.query.filter_by(organization_id=g.tenant.id, in_reply_to_id=item.id).all()
    ro = g.get("support_request") is not None
    return render_template("correspondence/detail.html", item=item, files=attachments_for("correspondence", item.id),
                           route_form=route_form, note_form=NoteForm(), action_form=ActionForm(), replies=replies,
                           can_handle=_can_handle(item) and not ro, can_approve=can("correspondence.approve") and not ro,
                           can_edit=(can("correspondence.manage") or item.created_by_id == current_user.id) and not ro,
                           can_comment=(current_user.id in _handlers(item) or can("correspondence.manage")) and not ro,
                           can_reply=can("correspondence.create") and not ro, today=date.today())


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    item = tenant_get_or_404(Correspondence, item_id)
    if not can_view_correspondence(item) or not (can("correspondence.manage") or item.created_by_id == current_user.id):
        abort(403)
    form = CorrespondenceForm(obj=item)
    _setup(form)
    del form.file
    if form.validate_on_submit():
        if form.assigned_to_id.data and not is_member(form.assigned_to_id.data):
            abort(400)
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        if form.kind.data != item.kind:
            form.kind.errors.append("The type cannot change once a reference number is issued.")
        else:
            old_assignee = item.assigned_to_id
            for f in ("subject", "party", "external_reference", "letter_date", "received_date", "summary", "priority",
                      "department_id", "assigned_to_id", "response_due"):
                setattr(item, f, getattr(form, f).data or None)
            item.priority = form.priority.data
            item.confidential = bool(form.confidential.data)
            if item.assigned_to_id != old_assignee and item.assigned_to_id:
                _log(item, "assigned", None, item.assigned_to_id)
                if item.status == "registered":
                    item.status = "assigned"
                notify([item.assigned_to_id], "correspondence", f"Assigned to you: {item.reference_no} {item.subject}",
                       None, "correspondence.detail", item_id=item.id)
            audit.record("correspondence.updated", f"{item.reference_no} updated", entity=item)
            db.session.commit()
            flash("Saved.", "success")
            return redirect(url_for("correspondence.detail", item_id=item.id))
    return render_template("correspondence/form.html", form=form, item=item, reply_to=None)


@bp.route("/<int:item_id>/route", methods=["POST"])
def route(item_id):
    item = tenant_get_or_404(Correspondence, item_id)
    if not can_view_correspondence(item) or not _can_handle(item) or item.archived:
        abort(403)
    form = RouteForm()
    form.to_user_id.choices = member_choices("— Choose —")
    if form.validate_on_submit() and form.to_user_id.data:
        if not is_member(form.to_user_id.data):
            abort(400)
        action = "assigned" if item.assigned_to_id is None else "forwarded"
        item.assigned_to_id = form.to_user_id.data
        if item.status in ("registered", "assigned", "responded"):
            item.status = "assigned"
        _log(item, action, form.note.data or None, item.assigned_to_id)
        notify([item.assigned_to_id], "correspondence",
               f"{'Forwarded' if action == 'forwarded' else 'Assigned'} to you: {item.reference_no} {item.subject}",
               form.note.data or None, "correspondence.detail", item_id=item.id)
        audit.record(f"correspondence.{action}", f"{item.reference_no} {action}", entity=item)
        db.session.commit()
        flash(f"Correspondence {action}.", "success")
    else:
        flash("Choose who to send it to.", "danger")
    return redirect(url_for("correspondence.detail", item_id=item.id))


@bp.route("/<int:item_id>/note", methods=["POST"])
def note(item_id):
    item = tenant_get_or_404(Correspondence, item_id)
    if not can_view_correspondence(item) or not (current_user.id in _handlers(item) or can("correspondence.manage")):
        abort(403)
    form = NoteForm()
    if form.validate_on_submit():
        _log(item, "comment", form.note.data)
        if item.status == "assigned" and item.assigned_to_id == current_user.id:
            item.status = "in_progress"
        notify(_handlers(item), "correspondence", f"New note on {item.reference_no}", form.note.data[:200],
               "correspondence.detail", item_id=item.id)
        db.session.commit()
    return redirect(url_for("correspondence.detail", item_id=item.id))


TRANSITIONS = {
    # action: (allowed from, to, who)
    "start": ({"assigned"}, "in_progress", "handler"),
    "submit": ({"assigned", "in_progress", "registered"}, "awaiting_approval", "handler"),
    "approve": ({"awaiting_approval"}, "approved", "approver"),
    "return": ({"awaiting_approval"}, "in_progress", "approver"),
    "respond": ({"assigned", "in_progress", "approved", "registered"}, "responded", "handler"),
    "close": (set(Correspondence.STATUSES) - {"closed"}, "closed", "handler"),
    "reopen": ({"closed"}, "in_progress", "manager"),
}


@bp.route("/<int:item_id>/do/<action>", methods=["POST"])
def transition(item_id, action):
    item = tenant_get_or_404(Correspondence, item_id)
    if not can_view_correspondence(item):
        abort(404)
    note_text = (request.form.get("note") or "").strip()[:2000] or None
    if not ActionForm().validate_on_submit():
        abort(400)
    if action in ("archive", "unarchive"):
        if not can("correspondence.manage"):
            abort(403)
        item.archived = action == "archive"
        _log(item, action, note_text)
    else:
        if action not in TRANSITIONS:
            abort(404)
        allowed, target, who = TRANSITIONS[action]
        ok_who = {"handler": _can_handle(item), "approver": can("correspondence.approve"),
                  "manager": can("correspondence.manage")}[who]
        if not ok_who or item.archived:
            abort(403)
        if item.status not in allowed:
            flash("That step is not available at this stage.", "warning")
            return redirect(url_for("correspondence.detail", item_id=item.id))
        item.status = target
        _log(item, action, note_text)
        if action == "submit":
            from app.models import Membership
            from app.rbac import permissions_for_role
            approvers = [m.user_id for m in Membership.query.filter_by(organization_id=g.tenant.id, status="active")
                         if m.role and "correspondence.approve" in permissions_for_role(m.role)]
            notify(approvers, "correspondence", f"Approval requested: {item.reference_no} {item.subject}", note_text,
                   "correspondence.detail", item_id=item.id)
        elif action in ("approve", "return"):
            notify(_handlers(item), "correspondence",
                   f"{item.reference_no} {'approved' if action == 'approve' else 'returned for changes'}", note_text,
                   "correspondence.detail", item_id=item.id)
    audit.record(f"correspondence.{action}", f"{item.reference_no}: {action}", entity=item)
    db.session.commit()
    flash("Updated.", "success")
    return redirect(url_for("correspondence.detail", item_id=item.id))
