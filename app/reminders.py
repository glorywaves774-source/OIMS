"""Scheduled reminders: run ``flask --app wsgi oims send-reminders`` hourly.

Each reminder is sent once per item and person (de-duplicated by key), so running the
command more often never produces repeats.
"""
from datetime import timedelta

from flask import g

from app.extensions import db
from app.models import (Activity, Correspondence, Document, Meeting, Milestone, Organization, Programme,
                        ProgrammeReport, Task, utcnow)
from app.notify import notify
from app.tenancy import clear_tenant, set_tenant


def run_reminders(now=None):
    """Must run inside a request context (the CLI command provides one) so links can be built."""
    now = now or utcnow()
    today = now.date()
    totals = {"tasks": 0, "overdue": 0, "meetings": 0, "documents": 0, "correspondence": 0, "activities": 0,
              "milestones": 0, "reports": 0}
    for org in Organization.query.filter_by(status=Organization.ACTIVE).all():
        set_tenant(org.id)
        g.tenant = org
        try:
            _org_reminders(org, now, today, totals)
            _programme_reminders(org, today, totals)
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



def _programme_reminders(org, today, totals):
    kw = {"organization_id": org.id, "exclude_current": False}
    for a in Activity.query.filter(Activity.organization_id == org.id, Activity.status == "planned",
                                   Activity.planned_start.isnot(None), Activity.planned_start <= today + timedelta(days=3),
                                   Activity.planned_start >= today):
        totals["activities"] += notify([a.responsible_id], "reminder", f"Activity starts {a.planned_start:%d %b}: {a.title}",
                                       None, "programmes.activity_detail", dedupe_key=f"act-start-{a.id}-{a.planned_start}",
                                       pid=a.programme_id, aid=a.id, org_slug=org.slug, **kw)
    for m in Milestone.query.filter(Milestone.organization_id == org.id, Milestone.achieved_date.is_(None),
                                    Milestone.due_date <= today + timedelta(days=7)):
        prog = db.session.get(Programme, m.programme_id) if m.programme_id else None
        if prog is None:
            continue
        label = "overdue" if m.due_date < today else f"due {m.due_date:%d %b}"
        totals["milestones"] += notify([prog.manager_id], "reminder", f"Milestone {label}: {m.title}", prog.code,
                                       "programmes.workplans", dedupe_key=f"ms-{m.id}-{m.due_date}-{'late' if m.due_date < today else 'soon'}",
                                       pid=prog.id, org_slug=org.slug, **kw)
    for r in ProgrammeReport.query.filter(ProgrammeReport.organization_id == org.id, ProgrammeReport.status == "draft",
                                          ProgrammeReport.due_date.isnot(None),
                                          ProgrammeReport.due_date <= today + timedelta(days=5)):
        prog = db.session.get(Programme, r.programme_id) if r.programme_id else None
        totals["reports"] += notify([r.prepared_by_id, prog.manager_id if prog else None], "reminder",
                                    f"Report due {r.due_date:%d %b}: {r.title}", None, "programmes.report_view",
                                    dedupe_key=f"rep-due-{r.id}-{r.due_date}", pid=r.programme_id, rid=r.id,
                                    org_slug=org.slug, **kw)
