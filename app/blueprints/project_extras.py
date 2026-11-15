"""Project management views: work breakdown, deliverables, risks and issues, and closure.

Risks and issues work for programmes and projects alike; the work breakdown structure,
deliverables and closure belong to projects only. Views are registered on both blueprints
by ``@route`` and turn away the kind they do not apply to.
"""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app import audit
from app.blueprints.programmes import child, ctx, independent_approver, load, need, owner_ep, route
from app.blueprints.tenant import is_member, member_choices
from app.extensions import db
from app.forms import ActionForm
from app.forms_programmes import (ClosureForm, ComponentForm, CorrectiveActionForm, DeliverableForm, IssueForm,
                                  ReviewNoteForm, RiskForm, WbsTaskForm)
from app.models import (Activity, Component, Deliverable, Expenditure, Indicator, IndicatorResult, Issue,
                        ProjectClosure, RiskItem, Task, utcnow)
from app.notify import notify
from app.programme_logic import can_do, of, own
from app.tenancy import tenant_get_or_404


def project_only(pid):
    prog = load(pid)
    if prog.kind != "project":
        abort(404)
    return prog


def _member(uid):
    if uid and not is_member(uid):
        abort(400)
    return uid or None


def _activity_choices(prog, blank="— None —"):
    return [(0, blank)] + [(a.id, f"{a.code + ' ' if a.code else ''}{a.title[:90]}") for a in Activity.query.filter(
        of(Activity, prog)).order_by(Activity.planned_start.is_(None), Activity.planned_start, Activity.id)]


def _component_choices(prog, blank="— None —"):
    return [(0, blank)] + [(c.id, f"{c.code + ' ' if c.code else ''}{c.title[:90]}")
                           for c in Component.query.filter_by(project_id=prog.id).order_by(Component.sort_order,
                                                                                           Component.id)]


def _back(prog, name, anchor=""):
    return redirect(url_for(owner_ep(prog, name), pid=prog.id) + anchor)


# ====================================================================================
# Work breakdown structure: project → components → activities → tasks → subtasks
# ====================================================================================

@route("/<int:pid>/wbs")
def wbs(pid):
    prog = project_only(pid)
    comps = Component.query.filter_by(project_id=prog.id).order_by(Component.sort_order, Component.id).all()
    acts = Activity.query.filter(of(Activity, prog)).order_by(Activity.planned_start.is_(None),
                                                               Activity.planned_start, Activity.id).all()
    tasks = Task.query.filter(Task.project_id == prog.id, Task.parent_id.is_(None),
                              Task.issue_id.is_(None), Task.risk_id.is_(None)).order_by(Task.due_date.is_(None),
                                                                                      Task.due_date, Task.id).all()
    dels = Deliverable.query.filter_by(project_id=prog.id).order_by(Deliverable.due_date.is_(None),
                                                                    Deliverable.due_date).all()
    tree = []
    for c in comps + [None]:
        cid = c.id if c else None
        node = {"c": c, "acts": [], "dels": [d for d in dels if d.component_id == cid and not d.activity_id]}
        for a in [a for a in acts if a.component_id == cid]:
            node["acts"].append({"a": a, "tasks": [t for t in tasks if t.activity_id == a.id],
                                 "dels": [d for d in dels if d.activity_id == a.id]})
        if c or node["acts"] or node["dels"]:
            tree.append(node)
    loose = [t for t in tasks if not t.activity_id]
    comp_form, task_form = ComponentForm(), WbsTaskForm()
    comp_form.responsible_id.choices = member_choices("— Not assigned —")
    _setup_task(task_form, prog)
    return render_template("programmes/wbs.html", tree=tree, loose=loose, comp_form=comp_form, task_form=task_form,
                           today=date.today(), **ctx(prog, "wbs"))


def _setup_task(form, prog):
    form.activity_id.choices = _activity_choices(prog, "— Not linked to an activity —")
    form.parent_id.choices = [(0, "— Top-level task —")] + [
        (t.id, t.title[:90]) for t in Task.query.filter(Task.project_id == prog.id, Task.parent_id.is_(None),
                                                         Task.status.in_(Task.OPEN)).order_by(Task.id)]
    form.assigned_to_id.choices = member_choices("— Me —")


@route("/<int:pid>/components/new", methods=["GET", "POST"], endpoint="component_new")
@route("/<int:pid>/components/<int:cid>/edit", methods=["GET", "POST"])
def component_edit(pid, cid=None):
    prog = project_only(pid)
    need("programmes.edit", prog)
    comp = child(Component, cid, prog) if cid else None
    form = ComponentForm(obj=comp)
    form.responsible_id.choices = member_choices("— Not assigned —")
    if form.validate_on_submit():
        if comp is None:
            last = db.session.scalar(select(func.max(Component.sort_order)).where(Component.project_id == prog.id))
            comp = Component(organization_id=g.tenant.id, project_id=prog.id, sort_order=(last or 0) + 1)
            db.session.add(comp)
        comp.code, comp.title = form.code.data or None, form.title.data
        comp.description, comp.responsible_id = form.description.data or None, _member(form.responsible_id.data)
        audit.record("project.component", f"{prog.code}: component '{comp.title}' saved", entity=prog)
        db.session.commit()
        flash("Component saved.", "success")
        return _back(prog, "wbs")
    return render_template("programmes/simple_form.html", form=form, title="Component" if comp else "New component",
                           back=url_for(owner_ep(prog, "wbs"), pid=prog.id), **ctx(prog, "wbs"))


@route("/<int:pid>/components/<int:cid>/delete", methods=["POST"])
def component_delete(pid, cid):
    prog = project_only(pid)
    need("programmes.edit", prog)
    comp = child(Component, cid, prog)
    if ActionForm().validate_on_submit():
        # Activities and deliverables stay; they simply move to "not in a component".
        audit.record("project.component_deleted", f"{prog.code}: component '{comp.title}' removed", entity=prog)
        for model in (Activity, Deliverable):
            model.query.filter_by(component_id=comp.id).update({"component_id": None}, synchronize_session=False)
        db.session.delete(comp)
        db.session.commit()
        flash("Component removed. Its activities and deliverables were kept.", "success")
    return _back(prog, "wbs")


@route("/<int:pid>/wbs/tasks", methods=["POST"])
def wbs_task(pid):
    prog = project_only(pid)
    need("programmes.edit", prog)
    form = WbsTaskForm()
    _setup_task(form, prog)
    if form.validate_on_submit():
        act = child(Activity, form.activity_id.data, prog) if form.activity_id.data else None
        parent = None
        if form.parent_id.data:
            parent = tenant_get_or_404(Task, form.parent_id.data)
            if parent.project_id != prog.id:
                abort(404)
        assignee = _member(form.assigned_to_id.data) or current_user.id
        t = Task(organization_id=g.tenant.id, title=form.title.data, priority=form.priority.data,
                 due_date=form.due_date.data, assigned_to_id=assignee, created_by_id=current_user.id,
                 project_id=prog.id, activity_id=(act.id if act else (parent.activity_id if parent else None)),
                 parent_id=parent.id if parent else None, department_id=prog.department_id)
        db.session.add(t)
        db.session.flush()
        if assignee != current_user.id:
            notify([assignee], "task", f"Task assigned to you: {t.title}", f"Project {prog.code}",
                   "tasks.detail", task_id=t.id)
        audit.record("task.created", f"{prog.code}: task '{t.title}' added", entity=t)
        db.session.commit()
        flash("Subtask added." if parent else "Task added.", "success")
    else:
        flash("The task was not added: " + "; ".join(e for errs in form.errors.values() for e in errs), "danger")
    return _back(prog, "wbs")


# ====================================================================================
# Deliverables
# ====================================================================================

def _can_submit(d, prog):
    return can_do("programmes.edit", prog) or (d.responsible_id == current_user.id
                                               and can_do("programmes.view", prog) and prog.status not in
                                               ("closed", "cancelled") and g.get("support_request") is None)


@route("/<int:pid>/deliverables")
def deliverables(pid):
    prog = project_only(pid)
    from app.blueprints.documents import attachments_for
    rows = Deliverable.query.filter_by(project_id=prog.id).order_by(Deliverable.due_date.is_(None),
                                                                    Deliverable.due_date, Deliverable.id).all()
    counts = {s: sum(1 for d in rows if d.status == s) for s in Deliverable.STATUSES}
    return render_template("programmes/deliverables.html", rows=rows, counts=counts, today=date.today(),
                           files={d.id: attachments_for("deliverable", d.id) for d in rows},
                           can_submit={d.id: _can_submit(d, prog) for d in rows}, note_form=ReviewNoteForm(),
                           **ctx(prog, "deliverables"))


@route("/<int:pid>/deliverables/new", methods=["GET", "POST"], endpoint="deliverable_new")
@route("/<int:pid>/deliverables/<int:did>/edit", methods=["GET", "POST"])
def deliverable_edit(pid, did=None):
    prog = project_only(pid)
    need("programmes.edit", prog)
    d = child(Deliverable, did, prog) if did else None
    if d and d.status == "verified":
        flash("A verified deliverable cannot be changed.", "warning")
        return _back(prog, "deliverables", f"#d{d.id}")
    form = DeliverableForm(obj=d)
    form.component_id.choices = _component_choices(prog)
    form.activity_id.choices = _activity_choices(prog)
    form.responsible_id.choices = member_choices("— Not assigned —")
    if form.validate_on_submit():
        if form.component_id.data:
            child(Component, form.component_id.data, prog)
        if form.activity_id.data:
            child(Activity, form.activity_id.data, prog)
        creating = d is None
        if creating:
            d = Deliverable(organization_id=g.tenant.id, project_id=prog.id)
            db.session.add(d)
        old_resp = d.responsible_id
        d.title, d.priority, d.due_date = form.title.data, form.priority.data, form.due_date.data
        d.description = form.description.data or None
        d.acceptance_criteria = form.acceptance_criteria.data or None
        d.component_id, d.activity_id = form.component_id.data or None, form.activity_id.data or None
        d.responsible_id = _member(form.responsible_id.data)
        d.reminder_sent_at = None
        db.session.flush()
        if d.responsible_id and d.responsible_id != old_resp and d.responsible_id != current_user.id:
            notify([d.responsible_id], "project", f"Deliverable assigned to you: {d.title}", f"Project {prog.code}",
                   owner_ep(prog, "deliverables"), pid=prog.id)
        audit.record("project.deliverable", f"{prog.code}: deliverable '{d.title}' {'added' if creating else 'updated'}",
                     entity=prog)
        db.session.commit()
        flash("Deliverable saved.", "success")
        return _back(prog, "deliverables", f"#d{d.id}")
    return render_template("programmes/simple_form.html", form=form,
                           title="Deliverable" if d else "New deliverable",
                           back=url_for(owner_ep(prog, "deliverables"), pid=prog.id),
                           attach=("deliverable", d.id, _files("deliverable", d.id)) if d else None,
                           **ctx(prog, "deliverables"))


def _files(kind, oid):
    from app.blueprints.documents import attachments_for
    return attachments_for(kind, oid)


@route("/<int:pid>/deliverables/<int:did>/<action>", methods=["POST"])
def deliverable_action(pid, did, action):
    prog = project_only(pid)
    d = child(Deliverable, did, prog)
    form = ReviewNoteForm()
    if not form.validate_on_submit():
        abort(400)
    note = form.note.data or None
    if action == "submit":
        if not _can_submit(d, prog) or d.status not in ("pending", "rejected"):
            abort(403)
        d.status, d.submitted_by_id, d.submitted_at, d.review_note = "submitted", current_user.id, utcnow(), note
        reviewers = {prog.manager_id} - {current_user.id, None}
        notify(reviewers, "project", f"Deliverable ready for checking: {d.title}", f"Project {prog.code}",
               owner_ep(prog, "deliverables"), pid=prog.id)
        msg = "Deliverable submitted for checking."
    elif action in ("verify", "reject"):
        need("programmes.manage", prog)
        if d.status != "submitted":
            abort(400)
        if d.submitted_by_id == current_user.id:
            flash("Someone other than the person who submitted it must check this deliverable.", "danger")
            return _back(prog, "deliverables", f"#d{d.id}")
        if action == "reject" and not note:
            flash("Say what needs to change before returning the deliverable.", "danger")
            return _back(prog, "deliverables", f"#d{d.id}")
        d.status = "verified" if action == "verify" else "rejected"
        d.verified_by_id, d.verified_at, d.review_note = current_user.id, utcnow(), note
        notify({d.submitted_by_id, d.responsible_id} - {None, current_user.id}, "project",
               f"Deliverable {d.status}: {d.title}", note, owner_ep(prog, "deliverables"), pid=prog.id)
        msg = "Deliverable accepted." if action == "verify" else "Deliverable returned for changes."
    elif action in ("cancel", "reopen"):
        need("programmes.manage", prog)
        if action == "cancel" and d.status == "verified":
            abort(400)
        if action == "reopen" and d.status != "cancelled":
            abort(400)
        d.status, d.review_note = ("cancelled" if action == "cancel" else "pending"), note
        msg = "Deliverable cancelled." if action == "cancel" else "Deliverable reopened."
    else:
        abort(404)
    audit.record(f"project.deliverable_{action}", f"{prog.code}: '{d.title}' → {d.status}", entity=prog)
    db.session.commit()
    flash(msg, "success")
    return _back(prog, "deliverables", f"#d{d.id}")


# ====================================================================================
# Risks and issues (programmes and projects)
# ====================================================================================

@route("/<int:pid>/risks")
def risks(pid):
    prog = load(pid)
    from app.blueprints.documents import attachments_for
    risk_rows = sorted(RiskItem.query.filter(of(RiskItem, prog)).all(),
                       key=lambda r: (r.status == "closed", -r.rating, r.id))
    issue_rows = Issue.query.filter(of(Issue, prog)).order_by(Issue.raised_on.desc(), Issue.id.desc()).all()
    order = {"open": 0, "in_progress": 1, "resolved": 2, "closed": 3}
    issue_rows.sort(key=lambda i: order.get(i.status, 9))
    actions = {}
    for t in Task.query.filter((Task.issue_id.in_([i.id for i in issue_rows] or [0]))
                               | (Task.risk_id.in_([r.id for r in risk_rows] or [0]))).order_by(Task.id):
        actions.setdefault(("issue", t.issue_id) if t.issue_id else ("risk", t.risk_id), []).append(t)
    matrix = [[sum(1 for r in risk_rows if r.status != "closed" and r.probability == p and r.impact == i)
               for i in range(1, 6)] for p in range(5, 0, -1)]
    action_form = CorrectiveActionForm()
    action_form.assigned_to_id.choices = member_choices("— Choose —")
    return render_template("programmes/risks.html", risk_rows=risk_rows, issue_rows=issue_rows, actions=actions,
                           matrix=matrix, today=date.today(), corrective_form=action_form,
                           files={i.id: attachments_for("issue", i.id) for i in issue_rows},
                           **ctx(prog, "risks"))


@route("/<int:pid>/risks/new", methods=["GET", "POST"], endpoint="risk_new")
@route("/<int:pid>/risks/<int:rid>/edit", methods=["GET", "POST"])
def risk_edit(pid, rid=None):
    prog = load(pid)
    need("programmes.edit", prog)
    r = child(RiskItem, rid, prog) if rid else None
    form = RiskForm(obj=r)
    form.owner_id.choices = member_choices("— Not assigned —")
    if form.validate_on_submit():
        creating = r is None
        if creating:
            r = RiskItem(organization_id=g.tenant.id, **own(prog))
            db.session.add(r)
        for f in ("code", "title", "description", "category", "probability", "impact", "mitigation", "status",
                  "review_date"):
            setattr(r, f, getattr(form, f).data or None)
        old_owner = r.owner_id
        r.owner_id = _member(form.owner_id.data)
        r.reminder_sent_at = None
        db.session.flush()
        if r.owner_id and r.owner_id != old_owner and r.owner_id != current_user.id:
            notify([r.owner_id], prog.kind, f"You own a risk on {prog.code}: {r.title}", None,
                   owner_ep(prog, "risks"), pid=prog.id)
        audit.record("risk.saved", f"{prog.code}: risk '{r.title}' (rating {r.rating})", entity=prog)
        db.session.commit()
        flash("Risk saved.", "success")
        return _back(prog, "risks", f"#r{r.id}")
    return render_template("programmes/simple_form.html", form=form, title="Risk" if r else "New risk",
                           back=url_for(owner_ep(prog, "risks"), pid=prog.id), **ctx(prog, "risks"))


@route("/<int:pid>/issues/new", methods=["GET", "POST"], endpoint="issue_new")
@route("/<int:pid>/issues/<int:iid>/edit", methods=["GET", "POST"])
def issue_edit(pid, iid=None):
    prog = load(pid)
    need("programmes.edit", prog)
    i = child(Issue, iid, prog) if iid else None
    form = IssueForm(obj=i)
    form.owner_id.choices = member_choices("— Not assigned —")
    form.risk_id.choices = [(0, "— None —")] + [(r.id, f"{r.code + ' ' if r.code else ''}{r.title[:80]}")
                                                for r in RiskItem.query.filter(of(RiskItem, prog)).order_by(RiskItem.id)]
    if form.validate_on_submit():
        if form.risk_id.data:
            child(RiskItem, form.risk_id.data, prog)
        if form.status.data in ("resolved", "closed") and not form.resolution.data:
            form.resolution.errors.append("Describe how the issue was resolved.")
        else:
            creating = i is None
            if creating:
                i = Issue(organization_id=g.tenant.id, raised_on=date.today(), raised_by_id=current_user.id, **own(prog))
                db.session.add(i)
            old_owner = i.owner_id
            i.title, i.description, i.severity = form.title.data, form.description.data or None, form.severity.data
            i.risk_id, i.owner_id = form.risk_id.data or None, _member(form.owner_id.data)
            if form.status.data in ("resolved", "closed") and i.status not in ("resolved", "closed"):
                i.resolved_on = date.today()
            elif form.status.data in Issue.OPEN:
                i.resolved_on = None
            i.status, i.resolution = form.status.data, form.resolution.data or None
            db.session.flush()
            if i.owner_id and i.owner_id != old_owner and i.owner_id != current_user.id:
                notify([i.owner_id], prog.kind, f"Issue on {prog.code} assigned to you: {i.title}", None,
                       owner_ep(prog, "risks"), pid=prog.id)
            audit.record("issue.saved", f"{prog.code}: issue '{i.title}' ({i.status})", entity=prog)
            db.session.commit()
            flash("Issue saved.", "success")
            return _back(prog, "risks", f"#i{i.id}")
    return render_template("programmes/simple_form.html", form=form, title="Issue" if i else "Raise an issue",
                           back=url_for(owner_ep(prog, "risks"), pid=prog.id) + "#issues",
                           attach=("issue", i.id, _files("issue", i.id)) if i else None, **ctx(prog, "risks"))


@route("/<int:pid>/<any(issue, risk):kind>/<int:oid>/actions", methods=["POST"])
def corrective_action(pid, kind, oid):
    prog = load(pid)
    need("programmes.edit", prog)
    obj = child(Issue if kind == "issue" else RiskItem, oid, prog)
    form = CorrectiveActionForm()
    form.assigned_to_id.choices = member_choices("— Choose —")
    if form.validate_on_submit():
        assignee = _member(form.assigned_to_id.data)
        t = Task(organization_id=g.tenant.id, title=form.title.data, priority=form.priority.data,
                 due_date=form.due_date.data, assigned_to_id=assignee, created_by_id=current_user.id,
                 project_id=prog.id if prog.kind == "project" else None, department_id=prog.department_id,
                 description=f"Corrective action for {kind} on {prog.code}: {obj.title}",
                 **{f"{kind}_id": obj.id})
        db.session.add(t)
        if kind == "issue" and obj.status == "open":
            obj.status = "in_progress"
        db.session.flush()
        if assignee != current_user.id:
            notify([assignee], "task", f"Corrective action assigned to you: {t.title}", f"{prog.code}",
                   "tasks.detail", task_id=t.id)
        audit.record("task.created", f"{prog.code}: corrective action '{t.title}'", entity=t)
        db.session.commit()
        flash("Corrective action added and assigned.", "success")
    else:
        flash("The action was not added: " + "; ".join(e for errs in form.errors.values() for e in errs), "danger")
    return _back(prog, "risks", f"#{kind[0]}{obj.id}")


# ====================================================================================
# Closure
# ====================================================================================

def closure_checklist(prog, closure=None):
    """Everything that must be settled before a project can be closed. Each check is computed, never ticked by hand."""
    dels = Deliverable.query.filter_by(project_id=prog.id).all()
    undone = [d for d in dels if d.status not in ("verified", "cancelled")]
    acts_open = Activity.query.filter(of(Activity, prog), Activity.status.in_(("planned", "in_progress",
                                                                               "postponed"))).count()
    tasks_open = Task.query.filter(Task.project_id == prog.id, Task.status.in_(Task.OPEN)).count()
    pending_spend = Expenditure.query.filter(of(Expenditure, prog), Expenditure.status == "pending").count()
    open_commit = Expenditure.query.filter(of(Expenditure, prog), Expenditure.kind == "commitment",
                                           Expenditure.status == "approved").count()
    issues_open = Issue.query.filter(of(Issue, prog), Issue.status.in_(Issue.OPEN)).count()
    results_unchecked = IndicatorResult.query.join(Indicator).filter(of(Indicator, prog),
                                                                     IndicatorResult.status == "submitted").count()
    c = closure
    checks = [
        ("deliverables", "All deliverables accepted or cancelled", not undone,
         f"{len(undone)} still open" if undone else f"{len(dels)} deliverable(s) settled"),
        ("activities", "All activities completed or cancelled", acts_open == 0,
         f"{acts_open} still open" if acts_open else "Done"),
        ("tasks", "No open project tasks", tasks_open == 0, f"{tasks_open} still open" if tasks_open else "Done"),
        ("expenditure", "No expenditure waiting for approval", pending_spend == 0,
         f"{pending_spend} waiting" if pending_spend else "Done"),
        ("commitments", "No open commitments (pay them or release them)", open_commit == 0,
         f"{open_commit} open" if open_commit else "Done"),
        ("issues", "No open issues", issues_open == 0, f"{issues_open} open" if issues_open else "Done"),
        ("results", "No indicator results waiting to be checked", results_unchecked == 0,
         f"{results_unchecked} waiting" if results_unchecked else "Done"),
        ("report", "Final report and financial reconciliation written",
         bool(c and c.final_report and c.financial_reconciliation), "Done" if c and c.final_report
         and c.financial_reconciliation else "Write them below"),
    ]
    return [{"key": k, "label": label, "ok": ok, "detail": detail} for k, label, ok, detail in checks]


@route("/<int:pid>/closure", methods=["GET", "POST"])
def closure(pid):
    prog = project_only(pid)
    c = ProjectClosure.query.filter_by(project_id=prog.id).first()
    editable = c is None or c.status in ("draft", "returned")
    form = ClosureForm(obj=c)
    if request.method == "POST":
        need("programmes.manage", prog)
        if not editable:
            abort(400)
        if form.validate_on_submit():
            if c is None:
                c = ProjectClosure(organization_id=g.tenant.id, project_id=prog.id)
                db.session.add(c)
            form.populate_obj(c)
            for f in form:
                if f.type == "TextAreaField" and not getattr(c, f.name):
                    setattr(c, f.name, None)
            audit.record("project.closure_saved", f"{prog.code}: closure report saved", entity=prog)
            db.session.commit()
            flash("Closure report saved.", "success")
            return _back(prog, "closure")
    checks = c.checklist_snapshot if c and c.status == "approved" else closure_checklist(prog, c)
    return render_template("programmes/closure.html", c=c, form=form, checks=checks, editable=editable,
                           ready=all(x["ok"] for x in checks), note_form=ReviewNoteForm(),
                           can_approve=can_do("programmes.manage", prog) and independent_approver(prog),
                           **ctx(prog, "closure"))


@route("/<int:pid>/closure/<any(submit, approve, return):action>", methods=["POST"])
def closure_action(pid, action):
    prog = project_only(pid)
    need("programmes.manage", prog)
    c = ProjectClosure.query.filter_by(project_id=prog.id).first()
    form = ReviewNoteForm()
    if c is None or not form.validate_on_submit():
        abort(400)
    checks = closure_checklist(prog, c)
    ready = all(x["ok"] for x in checks)
    note = form.note.data or None
    if action == "submit":
        if c.status not in ("draft", "returned"):
            abort(400)
        if prog.status not in ("active", "on_hold", "completed"):
            flash(f"Only an active, on-hold or completed project can be closed (this one is {prog.status}).", "danger")
            return _back(prog, "closure")
        if not ready:
            flash("Finish the open items on the checklist first.", "danger")
            return _back(prog, "closure")
        c.status, c.submitted_by_id, c.submitted_at, c.decision_note = "submitted", current_user.id, utcnow(), None
        from app.programme_logic import holders
        notify(set(holders("programmes.manage", prog)) - {current_user.id, prog.manager_id}, "project",
               f"Closure of {prog.code} needs approval", note, owner_ep(prog, "closure"), pid=prog.id)
        flash("Closure submitted for approval.", "success")
    elif action == "approve":
        if c.status != "submitted":
            abort(400)
        if not independent_approver(prog) or c.submitted_by_id == current_user.id:
            flash("Closure must be approved by someone other than the project manager and the person who submitted it.",
                  "danger")
            return _back(prog, "closure")
        if not ready:
            flash("Something changed since submission — the checklist is no longer complete.", "danger")
            return _back(prog, "closure")
        c.status, c.approved_by_id, c.approved_at, c.decision_note = "approved", current_user.id, utcnow(), note
        c.checklist_snapshot = checks
        old = prog.status
        prog.status, prog.closed_at, prog.status_note = "closed", utcnow(), "Closed after closure approval"
        notify(prog.member_ids() | {c.submitted_by_id}, "project", f"{prog.code} is closed",
               "The project is now a read-only archive.", owner_ep(prog, "overview"), pid=prog.id)
        audit.record("programme.status", f"{prog.code}: {old} → closed (closure approved)", entity=prog)
        flash("Closure approved. The project is now closed and kept as a read-only archive.", "success")
    else:  # return
        if c.status != "submitted":
            abort(400)
        if not note:
            flash("Say what needs to change before returning the closure.", "danger")
            return _back(prog, "closure")
        c.status, c.decision_note = "returned", note
        notify({c.submitted_by_id, prog.manager_id} - {None, current_user.id}, "project",
               f"Closure of {prog.code} returned for changes", note, owner_ep(prog, "closure"), pid=prog.id)
        flash("Closure returned for changes.", "success")
    audit.record(f"project.closure_{action}", f"{prog.code}: closure {c.status}", entity=prog)
    db.session.commit()
    return _back(prog, "closure")
