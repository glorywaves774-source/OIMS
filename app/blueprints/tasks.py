"""Tasks: assignment, priorities, deadlines, status and comments."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import case, or_, select

from app import audit
from app.blueprints.people import department_choices
from app.blueprints.tenant import (in_scope, is_member, member_choices, my_department_id, page_arg, scoped,
                                   workspace_blueprint)
from app.extensions import db
from app.forms_office import CommentForm, TaskForm, TaskStatusForm
from app.models import Department, Task, TaskComment, utcnow
from app.notify import notify
from app.rbac import can, require_permission
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("tasks", __name__, "/tasks")


def _owners(t):
    return tuple(u for u in (t.assigned_to_id, t.created_by_id) if u)


def work_owner(t):
    """The programme or project a task belongs to (directly, or through the issue or risk it corrects)."""
    from app.programme_logic import owner_of
    if t.project_id:
        return t.project
    for src in (t.issue, t.risk):
        if src is not None:
            return owner_of(src)
    return None


def _archived(t):
    o = work_owner(t)
    return o is not None and o.status in ("closed", "cancelled")


def can_view_task(t):
    if current_user.id in _owners(t):
        return True
    o = work_owner(t)
    if o is not None:
        from app.programme_logic import can_see
        if can_see("programmes.view", o):
            return True
    if t.meeting is not None:
        from app.blueprints.meetings import can_view_meeting
        if can_view_meeting(t.meeting):
            return True
    return can("tasks.view") and in_scope("tasks.view", t.department_id, _owners(t))


def can_update_status(t):
    if _archived(t):
        return False
    o = work_owner(t)
    if o is not None:
        from app.programme_logic import can_do
        if can_do("programmes.edit", o):
            return True
    return (t.assigned_to_id == current_user.id or t.created_by_id == current_user.id
            or (can("tasks.manage") and in_scope("tasks.manage", t.department_id, _owners(t))))


def can_edit_task(t):
    if _archived(t):
        return False
    o = work_owner(t)
    if o is not None:
        from app.programme_logic import can_do
        if can_do("programmes.edit", o):
            return True
    return t.created_by_id == current_user.id or (can("tasks.manage") and in_scope("tasks.manage", t.department_id, _owners(t)))


PRIORITY_ORDER = case({"urgent": 0, "high": 1, "normal": 2, "low": 3}, value=Task.priority, else_=4)


@bp.route("/")
@require_permission("tasks.view")
def index():
    view = request.args.get("view", "mine")
    status = request.args.get("status", "open")
    stmt = select(Task).where(Task.organization_id == g.tenant.id)
    if view == "mine":
        stmt = stmt.where(Task.assigned_to_id == current_user.id)
    elif view == "created":
        stmt = stmt.where(Task.created_by_id == current_user.id)
    else:
        view = "all"
        stmt = scoped(stmt, "tasks.view", dept_col=Task.department_id, own_cols=(Task.assigned_to_id, Task.created_by_id))
    if status == "open":
        stmt = stmt.where(Task.status.in_(Task.OPEN))
    elif status == "overdue":
        stmt = stmt.where(Task.status.in_(Task.OPEN), Task.due_date < date.today())
    elif status in Task.STATUSES:
        stmt = stmt.where(Task.status == status)
    q = (request.args.get("q") or "").strip()
    if q:
        stmt = stmt.where(or_(Task.title.ilike(f"%{q}%"), Task.description.ilike(f"%{q}%")))
    stmt = stmt.order_by(Task.due_date.is_(None), Task.due_date, PRIORITY_ORDER, Task.id)
    page = db.paginate(stmt, page=page_arg(), per_page=30, error_out=False)
    return render_template("tasks/index.html", page=page, view=view, status=status, q=q, today=date.today())


def _setup(form):
    form.assigned_to_id.choices = member_choices("— Me —")
    form.department_id.choices = department_choices()


@bp.route("/new", methods=["GET", "POST"])
@require_permission("tasks.create")
def new():
    form = TaskForm()
    _setup(form)
    if request.method == "GET":
        form.department_id.data = my_department_id()
    if form.validate_on_submit():
        assignee = form.assigned_to_id.data or current_user.id
        if not is_member(assignee):
            abort(400)
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        t = Task(organization_id=g.tenant.id, created_by_id=current_user.id, assigned_to_id=assignee,
                 title=form.title.data, description=form.description.data or None, priority=form.priority.data,
                 due_date=form.due_date.data, department_id=form.department_id.data)
        db.session.add(t)
        db.session.flush()
        notify([assignee], "task", f"New task: {t.title}",
               f"From {current_user.full_name}" + (f", due {t.due_date:%d %b %Y}" if t.due_date else ""),
               "tasks.detail", task_id=t.id)
        audit.record("task.created", f"Task '{t.title}' created", entity=t)
        db.session.commit()
        flash("Task created.", "success")
        return redirect(url_for("tasks.detail", task_id=t.id))
    return render_template("tasks/form.html", form=form, task=None)


@bp.route("/<int:task_id>")
def detail(task_id):
    t = tenant_get_or_404(Task, task_id)
    if not can_view_task(t):
        abort(404)
    from app.blueprints.documents import attachments_for
    ro = g.get("support_request") is not None
    owner = work_owner(t)
    return render_template("tasks/detail.html", t=t, files=attachments_for("task", t.id), owner=owner,
                           archived=_archived(t),
                           status_form=TaskStatusForm(obj=t), comment_form=CommentForm(), today=date.today(),
                           can_status=can_update_status(t) and not ro, can_edit=can_edit_task(t) and not ro, ro=ro)


@bp.route("/<int:task_id>/edit", methods=["GET", "POST"])
def edit(task_id):
    t = tenant_get_or_404(Task, task_id)
    if not can_view_task(t) or not can_edit_task(t):
        abort(403)
    form = TaskForm(obj=t)
    _setup(form)
    if form.validate_on_submit():
        new_assignee = form.assigned_to_id.data or current_user.id
        if not is_member(new_assignee):
            abort(400)
        if form.department_id.data:
            tenant_get_or_404(Department, form.department_id.data)
        reassigned = new_assignee != t.assigned_to_id
        t.title, t.description, t.priority = form.title.data, form.description.data or None, form.priority.data
        t.due_date, t.department_id, t.assigned_to_id = form.due_date.data, form.department_id.data, new_assignee
        t.reminder_sent_at = None
        if reassigned:
            notify([new_assignee], "task", f"Task assigned to you: {t.title}", None, "tasks.detail", task_id=t.id)
        audit.record("task.updated", f"Task '{t.title}' updated", entity=t)
        db.session.commit()
        flash("Task updated.", "success")
        return redirect(url_for("tasks.detail", task_id=t.id))
    return render_template("tasks/form.html", form=form, task=t)


@bp.route("/<int:task_id>/status", methods=["POST"])
def set_status(task_id):
    t = tenant_get_or_404(Task, task_id)
    if not can_view_task(t) or not can_update_status(t):
        abort(403)
    form = TaskStatusForm()
    if form.validate_on_submit() and form.status.data != t.status:
        old = t.status
        t.status = form.status.data
        t.completed_at = utcnow() if t.status == "done" else None
        notify(_owners(t), "task", f"Task {t.status.replace('_', ' ')}: {t.title}",
               f"Changed by {current_user.full_name}", "tasks.detail", task_id=t.id)
        audit.record("task.status", f"Task '{t.title}': {old} → {t.status}", entity=t)
        db.session.commit()
        flash("Status updated.", "success")
    return redirect(url_for("tasks.detail", task_id=t.id))


@bp.route("/<int:task_id>/comment", methods=["POST"])
def comment(task_id):
    t = tenant_get_or_404(Task, task_id)
    if not can_view_task(t) or g.get("support_request") is not None or _archived(t):
        abort(403)
    form = CommentForm()
    if form.validate_on_submit():
        t.comments.append(TaskComment(organization_id=g.tenant.id, author_id=current_user.id, body=form.body.data))
        notify(_owners(t), "task", f"New comment on: {t.title}", form.body.data[:200], "tasks.detail", task_id=t.id)
        db.session.commit()
    return redirect(url_for("tasks.detail", task_id=t.id) + "#comments")
