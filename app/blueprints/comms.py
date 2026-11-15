"""Notifications, announcements, internal messages and the calendar."""
import calendar as pycal
from datetime import date, datetime, time, timedelta, timezone

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select

from app import audit
from app.blueprints.people import department_choices
from app.blueprints.tenant import is_member, member_choices, my_department_id, page_arg, scoped, workspace_blueprint
from app.extensions import db
from app.forms import ActionForm
from app.forms_office import AnnouncementForm, NewMessageForm, ReplyForm
from app.models import (Announcement, Conversation, ConversationParticipant, Correspondence, Department, Document,
                        LeaveRequest, Meeting, Message, Notification, StaffProfile, Task, as_aware, utcnow)
from app.notify import notify
from app.rbac import can, require_permission
from app.security import is_safe_next
from app.tenancy import tenant_get_or_404
from app.timeutil import org_zone, to_local

bp = workspace_blueprint("comms", __name__)


# --- Notifications ---------------------------------------------------------------------

@bp.route("/notifications")
def notifications():
    stmt = (select(Notification).where(Notification.organization_id == g.tenant.id,
                                       Notification.user_id == current_user.id)
            .order_by(Notification.created_at.desc()))
    page = db.paginate(stmt, page=page_arg(), per_page=30, error_out=False)
    return render_template("comms/notifications.html", page=page, action_form=ActionForm())


@bp.route("/notifications/<int:note_id>")
def open_notification(note_id):
    n = tenant_get_or_404(Notification, note_id)
    if n.user_id != current_user.id:
        abort(404)
    if n.read_at is None and g.get("support_request") is None:
        n.read_at = utcnow()
        db.session.commit()
    return redirect(n.link if is_safe_next(n.link) else url_for("comms.notifications"))


@bp.route("/notifications/read-all", methods=["POST"])
def read_all():
    if ActionForm().validate_on_submit():
        Notification.query.filter(Notification.organization_id == g.tenant.id, Notification.user_id == current_user.id,
                                  Notification.read_at.is_(None)).update({"read_at": utcnow()}, synchronize_session=False)
        db.session.commit()
    return redirect(url_for("comms.notifications"))


# --- Announcements ------------------------------------------------------------------------

def visible_announcements(limit=None):
    today = date.today()
    q = Announcement.query.filter(Announcement.organization_id == g.tenant.id,
                                  or_(Announcement.expires_on.is_(None), Announcement.expires_on >= today))
    if not can("announcements.manage"):
        dept = my_department_id()
        q = q.filter(or_(Announcement.department_id.is_(None), Announcement.department_id == dept))
    q = q.order_by(Announcement.pinned.desc(), Announcement.created_at.desc())
    return q.limit(limit).all() if limit else q.all()


@bp.route("/announcements")
@require_permission("announcements.view")
def announcements():
    return render_template("comms/announcements.html", rows=visible_announcements(), action_form=ActionForm())


@bp.route("/announcements/new", methods=["GET", "POST"])
@bp.route("/announcements/<int:ann_id>/edit", methods=["GET", "POST"])
@require_permission("announcements.manage")
def announcement_edit(ann_id=None):
    ann = tenant_get_or_404(Announcement, ann_id) if ann_id else None
    form = AnnouncementForm(obj=ann)
    form.department_id.choices = department_choices("Everyone in the organization")
    if form.validate_on_submit():
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        creating = ann is None
        if creating:
            ann = Announcement(organization_id=g.tenant.id, author_id=current_user.id)
            db.session.add(ann)
        ann.title, ann.body, ann.department_id = form.title.data, form.body.data, form.department_id.data
        ann.pinned, ann.expires_on = form.pinned.data, form.expires_on.data
        db.session.flush()
        if creating:
            from app.models import Membership
            if ann.department_id:
                audience = [s.user_id for s in StaffProfile.query.filter_by(
                    organization_id=g.tenant.id, department_id=ann.department_id) if s.user_id]
            else:
                audience = [m.user_id for m in Membership.query.filter_by(organization_id=g.tenant.id, status="active")]
            notify(audience, "announcement", f"Announcement: {ann.title}", ann.body[:200], "comms.announcements")
        audit.record("announcement.published" if creating else "announcement.updated", f"Announcement '{ann.title}'",
                     entity=ann)
        db.session.commit()
        flash("Announcement published." if creating else "Announcement updated.", "success")
        return redirect(url_for("comms.announcements"))
    return render_template("comms/announcement_form.html", form=form, ann=ann)


@bp.route("/announcements/<int:ann_id>/delete", methods=["POST"])
@require_permission("announcements.manage")
def announcement_delete(ann_id):
    ann = tenant_get_or_404(Announcement, ann_id)
    if ActionForm().validate_on_submit():
        audit.record("announcement.deleted", f"Announcement '{ann.title}' deleted", entity=ann)
        db.session.delete(ann)
        db.session.commit()
        flash("Announcement removed.", "success")
    return redirect(url_for("comms.announcements"))


# --- Messages ---------------------------------------------------------------------------------

def _my_part(conv):
    return next((p for p in conv.participants if p.user_id == current_user.id), None)


@bp.route("/messages")
@require_permission("messages.use")
def inbox():
    parts = (ConversationParticipant.query.join(Conversation)
             .filter(ConversationParticipant.organization_id == g.tenant.id,
                     ConversationParticipant.user_id == current_user.id)
             .order_by(Conversation.last_message_at.desc()).all())
    rows = []
    for p in parts:
        conv = db.session.get(Conversation, p.conversation_id)
        last = (Message.query.filter_by(conversation_id=conv.id).order_by(Message.created_at.desc()).first())
        unread = last is not None and last.sender_id != current_user.id and (
            p.last_read_at is None or as_aware(last.created_at) > as_aware(p.last_read_at))
        others = [x.user.full_name for x in conv.participants if x.user_id != current_user.id]
        rows.append({"conv": conv, "last": last, "unread": unread, "others": others})
    return render_template("comms/inbox.html", rows=rows)


@bp.route("/messages/new", methods=["GET", "POST"])
@require_permission("messages.use")
def new_message():
    form = NewMessageForm()
    form.recipients.choices = [(uid, name) for uid, name in member_choices() if uid != current_user.id]
    if request.method == "GET" and request.args.get("to", type=int):
        form.recipients.data = [request.args.get("to", type=int)]
    if form.validate_on_submit():
        recipients = [u for u in form.recipients.data if is_member(u) and u != current_user.id]
        if not recipients:
            abort(400)
        now = utcnow()
        conv = Conversation(organization_id=g.tenant.id, subject=form.subject.data or None, last_message_at=now)
        db.session.add(conv)
        db.session.flush()
        for uid in [current_user.id] + recipients:
            conv.participants.append(ConversationParticipant(organization_id=g.tenant.id, user_id=uid,
                                                             last_read_at=now if uid == current_user.id else None))
        conv.messages.append(Message(organization_id=g.tenant.id, sender_id=current_user.id, body=form.body.data,
                                     created_at=now))
        notify(recipients, "message", f"Message from {current_user.full_name}",
               form.subject.data or form.body.data[:120], "comms.conversation", conv_id=conv.id)
        db.session.commit()
        return redirect(url_for("comms.conversation", conv_id=conv.id))
    return render_template("comms/new_message.html", form=form)


@bp.route("/messages/<int:conv_id>", methods=["GET", "POST"])
@require_permission("messages.use")
def conversation(conv_id):
    conv = tenant_get_or_404(Conversation, conv_id)
    mine = _my_part(conv)
    if mine is None:
        abort(404)
    form = ReplyForm()
    if form.validate_on_submit():
        now = utcnow()
        conv.messages.append(Message(organization_id=g.tenant.id, sender_id=current_user.id, body=form.body.data,
                                     created_at=now))
        conv.last_message_at = now
        mine.last_read_at = now
        notify([p.user_id for p in conv.participants], "message", f"Reply from {current_user.full_name}",
               form.body.data[:120], "comms.conversation", conv_id=conv.id)
        db.session.commit()
        return redirect(url_for("comms.conversation", conv_id=conv.id) + "#latest")
    mine.last_read_at = utcnow()
    db.session.commit()
    others = [p.user.full_name for p in conv.participants if p.user_id != current_user.id]
    return render_template("comms/conversation.html", conv=conv, form=form, others=others)


# --- Calendar -------------------------------------------------------------------------------

def calendar_events(start, end, scope):
    """Events between two dates for the chosen scope ('me', 'department' or 'organization')."""
    me = current_user.id
    dept = my_department_id()
    tz = org_zone()
    start_dt = datetime.combine(start, time.min, tz).astimezone(timezone.utc)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
    events = []

    if can("meetings.view"):
        from app.blueprints.meetings import visible_meetings_stmt
        stmt = visible_meetings_stmt().where(Meeting.starts_at >= start_dt, Meeting.starts_at < end_dt,
                                             Meeting.status != "cancelled")
        for m in db.session.execute(stmt).scalars():
            mine = m.organizer_id == me or any(p.user_id == me for p in m.participants)
            if scope == "me" and not mine:
                continue
            if scope == "department" and not (mine or (dept and m.department_id == dept)):
                continue
            loc = to_local(m.starts_at)
            events.append({"date": loc.date(), "time": loc.strftime("%H:%M"), "title": m.title, "kind": "meeting",
                           "url": url_for("meetings.detail", meeting_id=m.id)})

    if can("tasks.view"):
        stmt = select(Task).where(Task.organization_id == g.tenant.id, Task.due_date >= start, Task.due_date <= end,
                                  Task.status.in_(Task.OPEN))
        if scope == "me":
            stmt = stmt.where(Task.assigned_to_id == me)
        else:
            stmt = scoped(stmt, "tasks.view", dept_col=Task.department_id, own_cols=(Task.assigned_to_id, Task.created_by_id))
            if scope == "department":
                stmt = stmt.where(or_(Task.department_id == dept, Task.assigned_to_id == me))
        for t in db.session.execute(stmt).scalars():
            events.append({"date": t.due_date, "time": "", "title": f"Due: {t.title}", "kind": "task",
                           "url": url_for("tasks.detail", task_id=t.id)})

    if can("staff.view") and scope != "me":
        stmt = (select(LeaveRequest).join(StaffProfile, LeaveRequest.staff_id == StaffProfile.id)
                .where(LeaveRequest.organization_id == g.tenant.id, LeaveRequest.status == "approved",
                       LeaveRequest.start_date <= end, LeaveRequest.end_date >= start))
        if scope == "department":
            stmt = stmt.where(StaffProfile.department_id == dept)
        for lr in db.session.execute(stmt).scalars():
            d = max(lr.start_date, start)
            while d <= min(lr.end_date, end):
                if d.weekday() < 5:
                    events.append({"date": d, "time": "", "title": f"On leave: {lr.staff.full_name}", "kind": "leave",
                                   "url": url_for("leave.index")})
                d += timedelta(days=1)
    else:
        mine_staff = StaffProfile.query.filter_by(organization_id=g.tenant.id, user_id=me).first()
        if mine_staff:
            for lr in LeaveRequest.query.filter(LeaveRequest.staff_id == mine_staff.id, LeaveRequest.status == "approved",
                                                LeaveRequest.start_date <= end, LeaveRequest.end_date >= start):
                d = max(lr.start_date, start)
                while d <= min(lr.end_date, end):
                    if d.weekday() < 5:
                        events.append({"date": d, "time": "", "title": "My leave", "kind": "leave",
                                       "url": url_for("leave.index")})
                    d += timedelta(days=1)

    stmt = select(Correspondence).where(Correspondence.organization_id == g.tenant.id,
                                        Correspondence.response_due >= start, Correspondence.response_due <= end,
                                        Correspondence.status.notin_(("responded", "closed")),
                                        Correspondence.archived.is_(False), Correspondence.assigned_to_id == me)
    for c in db.session.execute(stmt).scalars():
        events.append({"date": c.response_due, "time": "", "title": f"Reply due: {c.reference_no}", "kind": "correspondence",
                       "url": url_for("correspondence.detail", item_id=c.id)})

    doc_stmt = select(Document).where(Document.organization_id == g.tenant.id, Document.expiry_date >= start,
                                      Document.expiry_date <= end, Document.status != "archived")
    if not (can("documents.manage") and scope == "organization"):
        doc_stmt = doc_stmt.where(Document.owner_id == me)
    for d in db.session.execute(doc_stmt).scalars():
        events.append({"date": d.expiry_date, "time": "", "title": f"Expires: {d.title}", "kind": "document",
                       "url": url_for("documents.detail", doc_id=d.id)})

    if can("programmes.view"):
        from app.models import Activity, Milestone
        from app.programme_logic import visible_programmes_stmt
        prog_ids = [p.id for p in db.session.execute(visible_programmes_stmt()).scalars()]
        if prog_ids:
            stmt = select(Activity).where(Activity.programme_id.in_(prog_ids), Activity.planned_start >= start,
                                          Activity.planned_start <= end, Activity.status.in_(Activity.OPEN))
            if scope == "me":
                stmt = stmt.where(Activity.responsible_id == me)
            for a in db.session.execute(stmt).scalars():
                events.append({"date": a.planned_start, "time": "", "title": f"Activity: {a.title}", "kind": "activity",
                               "url": url_for("programmes.activity_detail", pid=a.programme_id, aid=a.id)})
            if scope != "me":
                for m in Milestone.query.filter(Milestone.programme_id.in_(prog_ids), Milestone.due_date >= start,
                                                Milestone.due_date <= end, Milestone.achieved_date.is_(None)):
                    events.append({"date": m.due_date, "time": "", "title": f"Milestone: {m.title}", "kind": "milestone",
                                   "url": url_for("programmes.workplans", pid=m.programme_id) + "#milestones"})

    events.sort(key=lambda e: (e["date"], e["time"] or "99", e["title"]))
    return events


@bp.route("/calendar")
@require_permission("calendar.view")
def calendar():
    today = to_local(utcnow()).date()
    try:
        y, m = (int(x) for x in request.args.get("month", "").split("-"))
        first = date(y, m, 1)
    except ValueError:
        first = today.replace(day=1)
    scope = request.args.get("scope", "me")
    if scope not in ("me", "department", "organization"):
        scope = "me"
    last = date(first.year, first.month, pycal.monthrange(first.year, first.month)[1])
    events = calendar_events(first, last, scope)
    by_day = {}
    for e in events:
        by_day.setdefault(e["date"], []).append(e)
    weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(first.year, first.month)
    prev_m = (first - timedelta(days=1)).replace(day=1)
    next_m = (last + timedelta(days=1))
    return render_template("comms/calendar.html", first=first, weeks=weeks, by_day=by_day, events=events, today=today,
                           scope=scope, prev_m=prev_m, next_m=next_m)


def unread_messages_count():
    parts = ConversationParticipant.query.filter_by(organization_id=g.tenant.id, user_id=current_user.id).all()
    n = 0
    for p in parts:
        last = db.session.scalar(select(func.max(Message.created_at)).where(
            Message.conversation_id == p.conversation_id, Message.sender_id != current_user.id))
        if last and (p.last_read_at is None or as_aware(last) > as_aware(p.last_read_at)):
            n += 1
    return n
