"""Scheduled reminders: run ``flask --app wsgi oims send-reminders`` hourly.

Each reminder is sent once per item and person (de-duplicated by key), so running the
command more often never produces repeats.
"""
from datetime import timedelta

from flask import g

from app.extensions import db
from app.models import (Activity, Correspondence, Deliverable, Document, Meeting, Milestone, Organization,
                        Programme, ProgrammeReport, Project, RiskItem, Task, utcnow)
from app.notify import notify
from app.tenancy import clear_tenant, set_tenant


def run_reminders(now=None):
    """Must run inside a request context (the CLI command provides one) so links can be built."""
    now = now or utcnow()
    today = now.date()
    totals = {"tasks": 0, "overdue": 0, "meetings": 0, "documents": 0, "correspondence": 0, "activities": 0,
              "milestones": 0, "reports": 0, "deliverables": 0, "risks": 0, "feedback": 0}
    for org in Organization.query.filter_by(status=Organization.ACTIVE).all():
        set_tenant(org.id)
        g.tenant = org
        try:
            _org_reminders(org, now, today, totals)
            _programme_reminders(org, today, totals)
            _feedback_reminders(org, today, totals)
            db.session.commit()
        finally:
            clear_tenant()
            g.pop("tenant", None)
    return totals


def _org_reminders(org, now, today, totals):
    kw = {"organization_id": org.id, "exclude_current": False}
    for t in Task.query.filter(Task.organization_id == org.id, Task.status.in_(Task.OPEN),
                               Task.due_date.isnot(None), Task.due_date <= today + timedelta(days=1)):
        if t.due_date >= today:
            totals["tasks"] += notify([t.assigned_to_id], "reminder", f"Task due {'today' if t.due_date == today else 'tomorrow'}: {t.title}",
                                      None, "tasks.detail", dedupe_key=f"task-due-{t.id}-{t.due_date}", task_id=t.id,
                                      org_slug=org.slug, **kw)
        else:
            totals["overdue"] += notify([t.assigned_to_id, t.created_by_id], "reminder", f"Task overdue: {t.title}",
                                        f"It was due {t.due_date:%d %b %Y}.", "tasks.detail",
                                        dedupe_key=f"task-overdue-{t.id}-{t.due_date}", task_id=t.id,
                                        org_slug=org.slug, **kw)
    for m in Meeting.query.filter(Meeting.organization_id == org.id, Meeting.status == "scheduled",
                                  Meeting.starts_at > now, Meeting.starts_at <= now + timedelta(hours=24)):
        totals["meetings"] += notify([p.user_id for p in m.participants if p.response != "declined"], "reminder",
                                     f"Meeting within 24 hours: {m.title}", m.location, "meetings.detail",
                                     dedupe_key=f"meeting-{m.id}-{m.starts_at:%Y%m%d%H%M}", meeting_id=m.id,
                                     org_slug=org.slug, **kw)
    for d in Document.query.filter(Document.organization_id == org.id, Document.expiry_date.isnot(None),
                                   Document.expiry_date <= today + timedelta(days=30), Document.status != "archived"):
        label = "has expired" if d.expiry_date < today else f"expires on {d.expiry_date:%d %b %Y}"
        totals["documents"] += notify([d.owner_id], "reminder", f"Document {label}: {d.title}", None,
                                      "documents.detail", dedupe_key=f"doc-expiry-{d.id}-{d.expiry_date}", doc_id=d.id,
                                      org_slug=org.slug, **kw)
    for c in Correspondence.query.filter(Correspondence.organization_id == org.id, Correspondence.archived.is_(False),
                                         Correspondence.status.notin_(("responded", "closed")),
                                         Correspondence.response_due.isnot(None),
                                         Correspondence.response_due <= today + timedelta(days=2)):
        totals["correspondence"] += notify([c.assigned_to_id], "reminder",
                                           f"Response due {c.response_due:%d %b}: {c.reference_no} {c.subject}", None,
                                           "correspondence.detail", dedupe_key=f"corr-due-{c.id}-{c.response_due}",
                                           item_id=c.id, org_slug=org.slug, **kw)



def _owner(obj):
    """(programme or project, endpoint prefix) for a shared record; projects first."""
    if getattr(obj, "project_id", None):
        return db.session.get(Project, obj.project_id), "projects"
    if getattr(obj, "programme_id", None):
        return db.session.get(Programme, obj.programme_id), "programmes"
    return None, None


def _live(prog):
    return prog is not None and prog.status not in ("closed", "cancelled")


def _programme_reminders(org, today, totals):
    """Programme and project dates: activity starts, milestones, report deadlines, deliverables, risk reviews."""
    kw = {"organization_id": org.id, "exclude_current": False}
    for a in Activity.query.filter(Activity.organization_id == org.id, Activity.status == "planned",
                                   Activity.planned_start.isnot(None), Activity.planned_start <= today + timedelta(days=3),
                                   Activity.planned_start >= today):
        prog, perm = _owner(a)
        if not _live(prog):
            continue
        totals["activities"] += notify([a.responsible_id], "reminder", f"Activity starts {a.planned_start:%d %b}: {a.title}",
                                       prog.code, f"{perm}.activity_detail", dedupe_key=f"act-start-{a.id}-{a.planned_start}",
                                       pid=prog.id, aid=a.id, org_slug=org.slug, **kw)
    for m in Milestone.query.filter(Milestone.organization_id == org.id, Milestone.achieved_date.is_(None),
                                    Milestone.due_date <= today + timedelta(days=7)):
        prog, perm = _owner(m)
        if not _live(prog):
            continue
        label = "overdue" if m.due_date < today else f"due {m.due_date:%d %b}"
        totals["milestones"] += notify([prog.manager_id], "reminder", f"Milestone {label}: {m.title}", prog.code,
                                       f"{perm}.workplans", dedupe_key=f"ms-{m.id}-{m.due_date}-{'late' if m.due_date < today else 'soon'}",
                                       pid=prog.id, org_slug=org.slug, **kw)
    for r in ProgrammeReport.query.filter(ProgrammeReport.organization_id == org.id, ProgrammeReport.status == "draft",
                                          ProgrammeReport.due_date.isnot(None),
                                          ProgrammeReport.due_date <= today + timedelta(days=5)):
        prog, perm = _owner(r)
        if prog is None:
            continue
        totals["reports"] += notify([r.prepared_by_id, prog.manager_id], "reminder",
                                    f"Report due {r.due_date:%d %b}: {r.title}", prog.code, f"{perm}.report_view",
                                    dedupe_key=f"rep-due-{r.id}-{r.due_date}", pid=prog.id, rid=r.id,
                                    org_slug=org.slug, **kw)
    for d in Deliverable.query.filter(Deliverable.organization_id == org.id,
                                      Deliverable.status.in_(("pending", "rejected")), Deliverable.due_date.isnot(None),
                                      Deliverable.due_date <= today + timedelta(days=5)):
        prog = db.session.get(Project, d.project_id)
        if not _live(prog):
            continue
        label = "overdue" if d.due_date < today else f"due {d.due_date:%d %b}"
        totals["deliverables"] += notify([d.responsible_id or prog.manager_id], "reminder",
                                         f"Deliverable {label}: {d.title}", prog.code, "projects.deliverables",
                                         dedupe_key=f"del-{d.id}-{d.due_date}-{'late' if d.due_date < today else 'soon'}",
                                         pid=prog.id, org_slug=org.slug, **kw)
    for rk in RiskItem.query.filter(RiskItem.organization_id == org.id, RiskItem.status != "closed",
                                    RiskItem.review_date.isnot(None), RiskItem.review_date <= today + timedelta(days=2)):
        prog, perm = _owner(rk)
        if not _live(prog):
            continue
        totals["risks"] += notify([rk.owner_id or prog.manager_id], "reminder",
                                  f"Risk review {'overdue' if rk.review_date < today else 'due'}: {rk.title}", prog.code,
                                  f"{perm}.risks", dedupe_key=f"risk-rev-{rk.id}-{rk.review_date}",
                                  pid=prog.id, org_slug=org.slug, **kw)


def _feedback_reminders(org, today, totals):
    """Open feedback due tomorrow or already late: remind whoever handles it (or the handlers)."""
    from app.models import Feedback
    from app.programme_logic import holders
    kw = {"organization_id": org.id, "exclude_current": False}
    g.tenant = org
    for f in Feedback.query.filter(Feedback.organization_id == org.id, Feedback.status.in_(Feedback.OPEN),
                                   Feedback.due_date.isnot(None), Feedback.due_date <= today + timedelta(days=1)):
        people = [f.assigned_to_id] if f.assigned_to_id else holders("feedback.sensitive" if f.sensitive
                                                                     else "feedback.manage")
        late = f.due_date < today
        totals["feedback"] += notify(people, "reminder",
                                     f"{'Overdue' if late else 'Reply due'}: feedback {f.code}",
                                     None if f.sensitive else f.summary, "feedback.detail",
                                     dedupe_key=f"fb-{f.id}-{f.due_date}-{'late' if late else 'soon'}",
                                     fid=f.id, org_slug=org.slug, **kw)
