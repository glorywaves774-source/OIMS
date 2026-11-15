"""Feedback and complaints (accountability to affected people).

Feedback is recorded by staff or sent through an optional public page. Every case gets a reference,
a response deadline by priority, an owner, a response and a closing check of the person's
satisfaction. Safeguarding, fraud and misconduct reports are sensitive: only safeguarding staff (and
whoever took or handles the case) can open them.
"""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from app import audit
from app.blueprints.beneficiaries import location_choices, owner_choices, owner_key, parse_owner
from app.blueprints.tenant import member_choices, page_arg, workspace_blueprint
from app.crypto import decrypt_text, encrypt_text
from app.extensions import db, limiter
from app.forms_meal import (AssignForm, CloseFeedbackForm, FeedbackForm, FeedbackNoteForm, PublicFeedbackForm,
                            PublicSettingsForm, RespondForm)
from app.meal_logic import can_handle_feedback, can_see_beneficiary, can_see_feedback, visible_feedback_stmt
from app.models import Beneficiary, Feedback, FeedbackAction, Location, Organization
from app.notify import next_reference, notify
from app.programme_logic import holders, visible_owner_stmt
from app.rbac import ORG, can, require_permission, scope_of
from app.tenancy import clear_tenant, set_tenant, tenant_get_or_404

bp = workspace_blueprint("feedback", __name__, "/feedback")
public_bp = Blueprint("public_feedback", __name__, url_prefix="/f")


def _log(f, action, note=None, actor_id="me"):
    f.actions.append(FeedbackAction(organization_id=f.organization_id, action=action, note=note,
                                    actor_id=current_user.id if actor_id == "me" else actor_id))


def _handlers(f):
    """Who is told about new feedback: safeguarding staff for sensitive cases, otherwise feedback managers."""
    if f.sensitive:
        return set(holders("feedback.sensitive"))
    people = set(holders("feedback.manage"))
    if f.owner is not None and f.owner.manager_id:
        people.add(f.owner.manager_id)
    return people


def _due(received_on, priority):
    return received_on + timedelta(days=Feedback.RESPONSE_DAYS.get(priority, 7))


@bp.route("/")
def index():
    if not (can("feedback.view") or can("feedback.record")):
        abort(403)
    status = request.args.get("status") or "open"
    cat = request.args.get("category") or ""
    view = request.args.get("view") or "all"
    stmt = visible_feedback_stmt()
    if status == "open":
        stmt = stmt.where(Feedback.status.in_(Feedback.OPEN))
    elif status == "overdue":
        stmt = stmt.where(Feedback.status.in_(Feedback.OPEN), Feedback.due_date < date.today())
    elif status in Feedback.STATUSES:
        stmt = stmt.where(Feedback.status == status)
    if cat in Feedback.CATEGORIES:
        stmt = stmt.where(Feedback.category == cat)
    if view == "mine":
        stmt = stmt.where(Feedback.assigned_to_id == current_user.id)
    page = db.paginate(stmt.order_by(Feedback.due_date.is_(None), Feedback.due_date, Feedback.id.desc()),
                       page=page_arg(), per_page=30, error_out=False)
    return render_template("feedback/index.html", page=page, status=status, category=cat, view=view,
                           categories=Feedback.CATEGORIES, today=date.today(),
                           can_record=can("feedback.record") and not g.get("support_request"),
                           can_settings=_can_settings())


def _owner_options():
    return owner_choices([o for k in ("programme", "project") for o in db.session.execute(
        visible_owner_stmt(k).order_by("code")).scalars()], "— Not about a specific programme or project —")


@bp.route("/new", methods=["GET", "POST"])
@require_permission("feedback.record")
def new():
    if g.get("support_request"):
        abort(403)
    form = FeedbackForm()
    form.owner.choices = _owner_options()
    form.location_id.choices = location_choices()
    if request.method == "GET":
        form.received_on.data = date.today()
    if form.validate_on_submit():
        owner = parse_owner(form.owner.data) if form.owner.data else None
        if owner is not None and owner_key(owner) not in dict(form.owner.choices):
            abort(403)
        if form.location_id.data:
            tenant_get_or_404(Location, form.location_id.data)
        ben = None
        if form.beneficiary_code.data and not form.anonymous.data:
            ben = Beneficiary.query.filter_by(code=form.beneficiary_code.data.upper()).first()
            if ben is None or not can_see_beneficiary(ben):
                form.beneficiary_code.errors.append("No beneficiary with that code that you can see.")
        if form.received_on.data > date.today():
            form.received_on.errors.append("The date cannot be in the future.")
        if not form.errors:
            sensitive = form.category.data in Feedback.SENSITIVE
            priority = "high" if sensitive and form.priority.data in ("low", "normal") else form.priority.data
            anon = form.anonymous.data
            f = Feedback(organization_id=g.tenant.id, code=next_reference("FB"), channel=form.channel.data,
                         category=form.category.data, sensitive=sensitive, priority=priority,
                         received_on=form.received_on.data, received_by_id=current_user.id, source="staff",
                         location_id=form.location_id.data or None, beneficiary_id=ben.id if ben else None,
                         anonymous=anon, submitter_name=None if anon else (form.submitter_name.data or None),
                         contact_enc=None if anon else encrypt_text(form.contact.data),
                         wants_response=form.wants_response.data and not (anon and not form.contact.data),
                         summary=form.summary.data, description=form.description.data,
                         due_date=_due(form.received_on.data, priority), **({owner.fk: owner.id} if owner else {}))
            db.session.add(f)
            db.session.flush()
            _log(f, "received", f"Received by {current_user.full_name} ({Feedback.CHANNELS[f.channel]})")
            notify(_handlers(f) - {current_user.id}, "feedback",
                   f"{'Sensitive case' if sensitive else 'New feedback'} {f.code}",
                   None if sensitive else f.summary, "feedback.detail", fid=f.id)
            audit.record("feedback.recorded", f"Feedback {f.code} recorded{' (sensitive)' if sensitive else ''}",
                         entity=f)
            db.session.commit()
            flash(f"Recorded as {f.code}. Reply by {f.due_date:%d %b %Y}.", "success")
            return redirect(url_for("feedback.detail", fid=f.id) if can_see_feedback(f) else url_for("feedback.index"))
    return render_template("feedback/form.html", form=form)


def _load(fid):
    f = tenant_get_or_404(Feedback, fid)
    if not can_see_feedback(f):
        abort(404)
    return f


@bp.route("/<int:fid>")
def detail(fid):
    f = _load(fid)
    handle = can_handle_feedback(f)
    if f.sensitive:
        audit.record("feedback.viewed_sensitive", f"Sensitive case {f.code} opened", entity=f)
        db.session.commit()
    assign = AssignForm()
    assign.assigned_to_id.choices = _assignees(f)
    respond = RespondForm()
    respond.responded_on.data = date.today()
    return render_template("feedback/detail.html", f=f, handle=handle, contact=decrypt_text(f.contact_enc) if handle else None,
                           assign_form=assign, respond_form=respond, close_form=CloseFeedbackForm(),
                           note_form=FeedbackNoteForm(), today=date.today(), channels=Feedback.CHANNELS,
                           categories=Feedback.CATEGORIES, satisfaction=Feedback.SATISFACTION)


def _assignees(f):
    """Sensitive cases can only go to people with the sensitive permission."""
    people = member_choices()
    if f.sensitive:
        ok = set(holders("feedback.sensitive"))
        people = [(u, n) for u, n in people if u in ok]
    return [(0, "— Choose —")] + people


@bp.route("/<int:fid>/<any(acknowledge, assign, note, respond, close, reopen):action>", methods=["POST"])
def act(fid, action):
    f = _load(fid)
    if not can_handle_feedback(f):
        abort(403)
    back = redirect(url_for("feedback.detail", fid=f.id))
    if action == "acknowledge":
        if f.status != "new":
            abort(400)
        f.status = "acknowledged"
        _log(f, "acknowledged", request.form.get("note") or None)
    elif action == "assign":
        form = AssignForm()
        form.assigned_to_id.choices = _assignees(f)
        if not form.validate_on_submit() or not form.assigned_to_id.data:
            flash("Choose someone who can handle this case.", "danger")
            return back
        f.assigned_to_id = form.assigned_to_id.data
        if f.status in ("new", "acknowledged"):
            f.status = "in_progress"
        f.reminder_sent_at = None
        _log(f, "assigned", form.note.data or None)
        notify([f.assigned_to_id], "feedback", f"Case {f.code} assigned to you",
               None if f.sensitive else f.summary, "feedback.detail", fid=f.id)
    elif action == "note":
        form = FeedbackNoteForm()
        if not form.validate_on_submit():
            abort(400)
        _log(f, "note", form.note.data)
    elif action == "respond":
        form = RespondForm()
        if not form.validate_on_submit():
            flash("Write the response and its date.", "danger")
            return back
        if form.responded_on.data < f.received_on or form.responded_on.data > date.today():
            flash("The response date must be between the date received and today.", "danger")
            return back
        f.response, f.responded_on, f.status = form.response.data, form.responded_on.data, "responded"
        _log(f, "responded")
    elif action == "close":
        form = CloseFeedbackForm()
        if not form.validate_on_submit():
            abort(400)
        if f.wants_response and not f.response:
            flash("Record the response given to the person before closing.", "danger")
            return back
        f.status, f.closed_on, f.satisfaction = "closed", date.today(), form.satisfaction.data
        _log(f, "closed", form.note.data or None)
    elif action == "reopen":
        if f.status != "closed":
            abort(400)
        f.status, f.closed_on = "in_progress", None
        _log(f, "reopened", request.form.get("note") or None)
    audit.record(f"feedback.{action}", f"Feedback {f.code}: {action}", entity=f)
    db.session.commit()
    flash("Saved.", "success")
    return back


def _can_settings():
    return not g.get("support_request") and can("feedback.manage") and scope_of("feedback.manage") == ORG


@bp.route("/settings", methods=["GET", "POST"])
def settings():
    if not _can_settings():
        abort(403)
    org = g.tenant
    form = PublicSettingsForm(obj=org)
    if form.validate_on_submit():
        org.accept_public_feedback = form.accept_public_feedback.data
        org.public_feedback_intro = form.public_feedback_intro.data or None
        audit.record("feedback.public_page", "Public feedback page " +
                     ("switched on" if org.accept_public_feedback else "switched off"), entity=org)
        db.session.commit()
        flash("Saved.", "success")
        return redirect(url_for("feedback.settings"))
    return render_template("feedback/settings.html", form=form, org=org,
                           public_url=url_for("public_feedback.submit", org_slug=org.slug, _external=True))


# --- Public page (no sign-in) ------------------------------------------------------------------

@public_bp.route("/<org_slug>", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def submit(org_slug):
    org = Organization.query.filter_by(slug=org_slug).first()
    if org is None or not org.is_active or not org.accept_public_feedback:
        abort(404)
    form = PublicFeedbackForm()
    if form.validate_on_submit():
        if form.website.data:          # filled only by bots
            return render_template("feedback/public_done.html", org=org, code=None)
        set_tenant(org.id)
        try:
            sensitive = form.category.data in Feedback.SENSITIVE
            anon = form.anonymous.data
            f = Feedback(organization_id=org.id, code=next_reference("FB", organization_id=org.id),
                         channel="online", category=form.category.data, sensitive=sensitive,
                         priority="high" if sensitive else "normal", received_on=date.today(), source="public",
                         anonymous=anon, submitter_name=None if anon else (form.name.data or None),
                         contact_enc=None if anon else encrypt_text(form.contact.data),
                         wants_response=bool(form.contact.data) and not anon,
                         summary=(form.message.data[:120] + ("…" if len(form.message.data) > 120 else "")),
                         description=form.message.data + (f"\n\nCommunity: {form.community.data}"
                                                          if form.community.data else ""),
                         due_date=_due(date.today(), "high" if sensitive else "normal"))
            db.session.add(f)
            db.session.flush()
            f.actions.append(FeedbackAction(organization_id=org.id, action="received", note="Sent through the public page"))
            g.tenant = org
            notify(_handlers(f), "feedback", f"{'Sensitive case' if sensitive else 'New feedback'} {f.code}",
                   None if sensitive else f.summary, "feedback.detail", organization_id=org.id,
                   exclude_current=False, fid=f.id, org_slug=org.slug)
            audit.record("feedback.public", f"Feedback {f.code} received through the public page",
                         entity=f, organization_id=org.id)
            db.session.commit()
            code = f.code
        finally:
            clear_tenant()
            g.pop("tenant", None)
        return render_template("feedback/public_done.html", org=org, code=code)
    return render_template("feedback/public.html", form=form, org=org)
