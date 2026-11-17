"""Meetings: scheduling, invitations, attendance, minutes, decisions and action points."""
from datetime import timedelta

from flask import abort, flash, g, jsonify, make_response, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import exists, or_, select

from app import audit, video
from app.blueprints.people import department_choices
from app.blueprints.tenant import is_member, member_choices, my_department_id, page_arg, workspace_blueprint
from app.extensions import db, limiter
from app.forms import ActionForm
from app.forms_office import ActionPointForm, DecisionTextForm, MeetingForm, MinutesForm
from app.models import Department, Meeting, MeetingDecision, MeetingParticipant, Task, as_aware, utcnow
from app.notify import notify
from app.rbac import DEPT, ORG, can, require_permission, scope_of
from app.tenancy import tenant_get_or_404
from app.timeutil import local_naive, to_utc

bp = workspace_blueprint("meetings", __name__, "/meetings")


def _is_participant(m):
    return any(p.user_id == current_user.id for p in m.participants)


def can_view_meeting(m):
    if m.organizer_id == current_user.id or _is_participant(m) or can("meetings.manage"):
        return True
    scope = scope_of("meetings.view")
    return scope == ORG or (scope == DEPT and m.department_id is not None and m.department_id == my_department_id())


def _can_manage(m):
    return (m.organizer_id == current_user.id or can("meetings.manage")) and g.get("support_request") is None


def visible_meetings_stmt():
    stmt = select(Meeting).where(Meeting.organization_id == g.tenant.id)
    if can("meetings.manage") or scope_of("meetings.view") == ORG:
        return stmt
    me = current_user.id
    conds = [Meeting.organizer_id == me,
             exists().where(MeetingParticipant.meeting_id == Meeting.id, MeetingParticipant.user_id == me)]
    if scope_of("meetings.view") == DEPT and my_department_id():
        conds.append(Meeting.department_id == my_department_id())
    return stmt.where(or_(*conds))


@bp.route("/")
@require_permission("meetings.view")
def index():
    when = request.args.get("when", "upcoming")
    now = utcnow()
    stmt = visible_meetings_stmt()
    if when == "past":
        stmt = stmt.where(Meeting.starts_at < now).order_by(Meeting.starts_at.desc())
    else:
        stmt = stmt.where(Meeting.starts_at >= now - timedelta(hours=12)).order_by(Meeting.starts_at)
    page = db.paginate(stmt, page=page_arg(), per_page=25, error_out=False)
    return render_template("meetings/index.html", page=page, when=when)


def _setup(form):
    form.department_id.choices = department_choices()
    form.participants.choices = member_choices()


def _sync_participants(meeting, wanted_ids):
    wanted = {uid for uid in wanted_ids if is_member(uid)}
    if meeting.organizer_id:
        wanted.add(meeting.organizer_id)
    have = {p.user_id: p for p in meeting.participants}
    for uid, p in have.items():
        if uid not in wanted:
            meeting.participants.remove(p)
    added = wanted - set(have)
    for uid in added:
        meeting.participants.append(MeetingParticipant(organization_id=g.tenant.id, user_id=uid,
                                                       response="accepted" if uid == meeting.organizer_id else "invited"))
    return added


@bp.route("/new", methods=["GET", "POST"])
@bp.route("/<int:meeting_id>/edit", methods=["GET", "POST"])
@require_permission("meetings.view")
def edit(meeting_id=None):
    meeting = tenant_get_or_404(Meeting, meeting_id) if meeting_id else None
    if meeting is None and not can("meetings.create"):
        abort(403)
    if meeting is not None and not (can_view_meeting(meeting) and _can_manage(meeting)):
        abort(403)
    form = MeetingForm(obj=meeting)
    _setup(form)
    if request.method == "GET":
        if meeting:
            form.starts_at.data, form.ends_at.data = local_naive(meeting.starts_at), local_naive(meeting.ends_at)
            form.participants.data = [p.user_id for p in meeting.participants]
            form.video_call.data = bool(meeting.video_room)
        else:
            form.department_id.data = my_department_id()
    if form.validate_on_submit():
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        creating = meeting is None
        if creating:
            meeting = Meeting(organization_id=g.tenant.id, organizer_id=current_user.id)
            db.session.add(meeting)
        changed_time = not creating and to_utc(form.starts_at.data) != as_aware(meeting.starts_at)
        for f in ("title", "meeting_type", "location", "online_link", "agenda", "department_id"):
            setattr(meeting, f, getattr(form, f).data or None)
        meeting.starts_at, meeting.ends_at = to_utc(form.starts_at.data), to_utc(form.ends_at.data)
        if form.video_call.data and video.enabled():
            meeting.video_room = meeting.video_room or video.new_room()   # the room keeps its name once made
        elif not form.video_call.data:
            meeting.video_room = None
        if changed_time:
            meeting.reminder_sent_at = None
        db.session.flush()
        added = _sync_participants(meeting, form.participants.data or [])
        when = form.starts_at.data.strftime("%a %d %b %Y, %H:%M")
        notify(added, "meeting", f"Meeting invitation: {meeting.title}", f"{when} · {meeting.location or 'Online'}",
               "meetings.detail", meeting_id=meeting.id)
        if changed_time:
            notify([p.user_id for p in meeting.participants if p.user_id not in added], "meeting",
                   f"Meeting rescheduled: {meeting.title}", f"New time: {when}", "meetings.detail", meeting_id=meeting.id)
        audit.record("meeting.scheduled" if creating else "meeting.updated", f"Meeting '{meeting.title}' saved", entity=meeting)
        db.session.commit()
        flash("Meeting saved and invitations sent." if creating else "Meeting updated.", "success")
        return redirect(url_for("meetings.detail", meeting_id=meeting.id))
    return render_template("meetings/form.html", video_on=video.enabled(), form=form, meeting=meeting)


@bp.route("/<int:meeting_id>")
@require_permission("meetings.view")
def detail(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not can_view_meeting(m):
        abort(404)
    from app.blueprints.documents import attachments_for
    actions = Task.query.filter_by(organization_id=g.tenant.id, meeting_id=m.id).order_by(Task.due_date).all()
    ap_form = ActionPointForm()
    ap_form.assigned_to_id.choices = [(0, "— Choose —")] + [(p.user_id, p.user.full_name) for p in m.participants]
    mine = next((p for p in m.participants if p.user_id == current_user.id), None)
    resp = make_response(render_template(
        "meetings/detail.html", m=m, actions=actions, files=attachments_for("meeting", m.id),
        manage=_can_manage(m), mine=mine, minutes_form=MinutesForm(obj=m), decision_form=DecisionTextForm(),
        ap_form=ap_form, action_form=ActionForm(), ro=g.get("support_request") is not None,
        video_on=video.enabled(), link_label=video.link_label))
    # live notes listen through this device's microphone
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(self), geolocation=()"
    return resp


def _call_headers(resp):
    """The call page may show the video service in a frame and use the camera and microphone."""
    from app.security import CSP
    src = video.origin() if video.embedded() else None
    resp.headers["Content-Security-Policy"] = CSP.replace("object-src 'none'", f"object-src 'none'; frame-src {src}") \
        if src else CSP
    allow = f'(self "{src}")' if src else "(self)"
    resp.headers["Permissions-Policy"] = (f"camera={allow}, microphone={allow}, display-capture={allow}, "
                                          f"fullscreen={allow}, geolocation=()")
    return resp


def _present(m):
    people = [p for p in m.participants if p.attended] or [p for p in m.participants if p.response == "accepted"]
    return [p.user.full_name for p in people]


@bp.route("/<int:meeting_id>/video", methods=["POST"])
@require_permission("meetings.view")
def start_video(meeting_id):
    """Adds a video call to a meeting that has none yet, then opens it."""
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m) or m.status == "cancelled" or not video.enabled() or not ActionForm().validate_on_submit():
        abort(403)
    if not m.video_room:
        m.video_room = video.new_room()
        audit.record("meeting.video_added", f"Video call added to '{m.title}'", entity=m)
        db.session.commit()
    return redirect(url_for("meetings.call", meeting_id=m.id))


@bp.route("/<int:meeting_id>/call")
@require_permission("meetings.view")
def call(meeting_id):
    """The video call (inside the page, or a button that opens it in its own tab) with the live notes beside it."""
    from app.i18n import current_language
    m = tenant_get_or_404(Meeting, meeting_id)
    if not can_view_meeting(m) or not m.video_room or m.status == "cancelled" or not video.enabled():
        abort(404)
    manage = _can_manage(m)
    url = video.join_url(m.video_room, f"{g.tenant.id}-{current_user.id}", current_user.full_name,
                         moderator=manage or m.organizer_id == current_user.id, lang=current_language())
    audit.record("meeting.call_joined", f"Joined the video call of '{m.title}'", entity=m)
    db.session.commit()
    resp = make_response(render_template("meetings/call.html", m=m, join_url=url, embedded=video.embedded(),
                                         manage=manage, minutes_form=MinutesForm(obj=m)))
    resp.headers["Cache-Control"] = "no-store"   # the page holds a personal pass to the call
    return _call_headers(resp)


@bp.route("/<int:meeting_id>/notes", methods=["POST"])
@require_permission("meetings.view")
@limiter.limit("120 per hour")
def save_notes(meeting_id):
    """Keeps the live notes on the server while they are being taken (so nothing is lost if a phone sleeps)."""
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m):
        abort(403)
    text = ((request.get_json(silent=True) or {}).get("transcript") or "")[:60000]
    m.transcript = text or None
    m.transcript_updated_at = utcnow()
    db.session.commit()
    return jsonify(saved=True)


@bp.route("/<int:meeting_id>/notes/draft", methods=["POST"])
@require_permission("meetings.view")
@limiter.limit("20 per hour")
def draft_notes(meeting_id):
    """Turns the notes into draft minutes. Nothing is saved: the draft goes into the minutes box for checking."""
    from app.i18n import current_language
    from app.notes import draft_minutes
    from app.timeutil import local_naive as _local
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m):
        abort(403)
    text = ((request.get_json(silent=True) or {}).get("transcript") or "")[:60000]
    if not text.strip():
        return jsonify(error="empty"), 400
    m.transcript, m.transcript_updated_at = text, utcnow()
    lang = current_language()
    when = _local(m.starts_at).strftime("%d/%m/%Y %H:%M") if m.starts_at else ""
    draft, source = draft_minutes(text, lang, title=m.title, when=when, present=_present(m), agenda=m.agenda or "")
    audit.record("meeting.minutes_drafted", f"Minutes drafted from notes for '{m.title}' ({source})", entity=m)
    db.session.commit()
    return jsonify(draft=draft, source=source)


@bp.route("/<int:meeting_id>/report")
@require_permission("meetings.view")
def report(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not can_view_meeting(m):
        abort(404)
    actions = Task.query.filter_by(organization_id=g.tenant.id, meeting_id=m.id).order_by(Task.due_date).all()
    return render_template("meetings/report.html", m=m, actions=actions)


@bp.route("/<int:meeting_id>/rsvp/<answer>", methods=["POST"])
@require_permission("meetings.view")
def rsvp(meeting_id, answer):
    m = tenant_get_or_404(Meeting, meeting_id)
    mine = next((p for p in m.participants if p.user_id == current_user.id), None)
    if mine is None or answer not in ("accepted", "declined") or not ActionForm().validate_on_submit():
        abort(403)
    mine.response = answer
    if m.organizer_id:
        notify([m.organizer_id], "meeting", f"{current_user.full_name} {answer} '{m.title}'", None,
               "meetings.detail", meeting_id=m.id)
    db.session.commit()
    flash("Response saved.", "success")
    return redirect(url_for("meetings.detail", meeting_id=m.id))


@bp.route("/<int:meeting_id>/attendance", methods=["POST"])
@require_permission("meetings.view")
def attendance(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m) or not ActionForm().validate_on_submit():
        abort(403)
    present = set(request.form.getlist("present", type=int))
    for p in m.participants:
        p.attended = p.user_id in present
    if m.status == "scheduled" and as_aware(m.starts_at) <= utcnow() + timedelta(hours=1):
        m.status = "held"
    audit.record("meeting.attendance", f"Attendance recorded for '{m.title}' ({len(present)} present)", entity=m)
    db.session.commit()
    flash("Attendance saved.", "success")
    return redirect(url_for("meetings.detail", meeting_id=m.id) + "#attendance")


@bp.route("/<int:meeting_id>/minutes", methods=["POST"])
@require_permission("meetings.view")
def minutes(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m):
        abort(403)
    form = MinutesForm()
    if form.validate_on_submit():
        m.minutes = form.minutes.data or None
        m.minutes_recorded_by_id = current_user.id
        if m.status == "scheduled" and as_aware(m.starts_at) <= utcnow():
            m.status = "held"
        audit.record("meeting.minutes", f"Minutes saved for '{m.title}'", entity=m)
        db.session.commit()
        flash("Minutes saved.", "success")
    return redirect(url_for("meetings.detail", meeting_id=m.id) + "#minutes")


@bp.route("/<int:meeting_id>/decision", methods=["POST"])
@require_permission("meetings.view")
def decision(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m):
        abort(403)
    form = DecisionTextForm()
    if form.validate_on_submit():
        m.decisions.append(MeetingDecision(organization_id=g.tenant.id, text=form.text.data))
        audit.record("meeting.decision", f"Decision recorded for '{m.title}'", entity=m)
        db.session.commit()
    return redirect(url_for("meetings.detail", meeting_id=m.id) + "#decisions")


@bp.route("/<int:meeting_id>/action", methods=["POST"])
@require_permission("meetings.view")
def action_point(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m):
        abort(403)
    form = ActionPointForm()
    form.assigned_to_id.choices = [(0, "— Choose —")] + [(p.user_id, p.user.full_name) for p in m.participants]
    if form.validate_on_submit():
        task = Task(organization_id=g.tenant.id, title=form.title.data, assigned_to_id=form.assigned_to_id.data,
                    due_date=form.due_date.data, created_by_id=current_user.id, department_id=m.department_id,
                    meeting_id=m.id, description=f"Action point from the meeting '{m.title}'.")
        db.session.add(task)
        db.session.flush()
        notify([task.assigned_to_id], "task", f"Action point assigned to you: {task.title}",
               f"From the meeting '{m.title}'", "tasks.detail", task_id=task.id)
        audit.record("meeting.action_point", f"Action point '{task.title}' added", entity=m)
        db.session.commit()
        flash("Action point added and assigned as a task.", "success")
    else:
        flash("Give the action point a title and a responsible person.", "danger")
    return redirect(url_for("meetings.detail", meeting_id=m.id) + "#actions")


@bp.route("/<int:meeting_id>/cancel", methods=["POST"])
@require_permission("meetings.view")
def cancel(meeting_id):
    m = tenant_get_or_404(Meeting, meeting_id)
    if not _can_manage(m) or not ActionForm().validate_on_submit() or m.status != "scheduled":
        abort(403)
    m.status = "cancelled"
    notify([p.user_id for p in m.participants], "meeting", f"Meeting cancelled: {m.title}", None,
           "meetings.detail", meeting_id=m.id)
    audit.record("meeting.cancelled", f"Meeting '{m.title}' cancelled", entity=m)
    db.session.commit()
    flash("Meeting cancelled and participants notified.", "success")
    return redirect(url_for("meetings.detail", meeting_id=m.id))
