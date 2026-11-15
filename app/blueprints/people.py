"""Departments, staff & HR records, leave and attendance."""
from datetime import date, datetime, timedelta

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select

from app import audit
from app.blueprints.tenant import (in_scope, member_choices, my_department_id, my_staff, page_arg,
                                   scoped, workspace_blueprint)
from app.extensions import db
from app.forms import ActionForm
from app.forms_office import (ATTENDANCE_CHOICES, DecisionForm, DepartmentForm, ExitForm, LeaveRequestForm,
                              LeaveTypeForm, ReviewForm, StaffForm, TrainingForm, TransferForm)
from app.models import (AttendanceRecord, Department, Document, LeaveRequest, LeaveType, Membership,
                        PerformanceReview, StaffProfile, StaffTransfer, TrainingRecord, utcnow)
from app.notify import notify, working_days
from app.rbac import can, require_permission, scope_of
from app.tenancy import tenant_get_or_404

departments_bp = workspace_blueprint("departments", __name__, "/departments")
staff_bp = workspace_blueprint("staff", __name__, "/staff")
leave_bp = workspace_blueprint("leave", __name__, "/leave")
attendance_bp = workspace_blueprint("attendance", __name__, "/attendance")


def department_choices(blank="— None —", active_only=True):
    q = Department.query.filter_by(organization_id=g.tenant.id)
    if active_only:
        q = q.filter_by(is_active=True)
    return [(0, blank)] + [(d.id, d.name) for d in q.order_by(Department.name)]


def staff_choices(blank="— None —"):
    rows = (StaffProfile.query.filter(StaffProfile.organization_id == g.tenant.id, StaffProfile.status != "exited")
            .order_by(StaffProfile.full_name))
    return [(0, blank)] + [(s.id, f"{s.full_name} ({s.employee_number})") for s in rows]


# ====================================================================================
# Departments
# ====================================================================================

@departments_bp.route("/")
@require_permission("departments.view")
def index():
    show_all = request.args.get("all") == "1"
    q = Department.query.filter_by(organization_id=g.tenant.id)
    if not show_all:
        q = q.filter_by(is_active=True)
    rows = q.order_by(Department.name).all()
    counts = dict(db.session.execute(
        select(StaffProfile.department_id, func.count()).where(
            StaffProfile.organization_id == g.tenant.id, StaffProfile.status != "exited")
        .group_by(StaffProfile.department_id)).all())
    return render_template("people/departments.html", rows=rows, counts=counts, show_all=show_all)


@departments_bp.route("/new", methods=["GET", "POST"])
@departments_bp.route("/<int:dept_id>/edit", methods=["GET", "POST"])
@require_permission("departments.manage")
def edit(dept_id=None):
    dept = tenant_get_or_404(Department, dept_id) if dept_id else None
    form = DepartmentForm(obj=dept)
    form.head_staff_id.choices = staff_choices()
    if form.validate_on_submit():
        clash = Department.query.filter(Department.organization_id == g.tenant.id, Department.name == form.name.data,
                                        Department.id != (dept.id if dept else 0)).first()
        if clash:
            form.name.errors.append("Another department already has this name.")
        else:
            head = tenant_get_or_404(StaffProfile, form.head_staff_id.data) if form.head_staff_id.data else None
            creating = dept is None
            if creating:
                dept = Department(organization_id=g.tenant.id)
                db.session.add(dept)
            dept.name, dept.code = form.name.data, form.code.data or None
            dept.description, dept.responsibilities = form.description.data or None, form.responsibilities.data or None
            dept.head_staff_id = head.id if head else None
            db.session.flush()
            audit.record("department.created" if creating else "department.updated", f"Department {dept.name} saved", entity=dept)
            db.session.commit()
            flash("Department saved.", "success")
            return redirect(url_for("departments.detail", dept_id=dept.id))
    return render_template("people/department_form.html", form=form, dept=dept)


@departments_bp.route("/<int:dept_id>")
@require_permission("departments.view")
def detail(dept_id):
    dept = tenant_get_or_404(Department, dept_id)
    staff = []
    if can("staff.view"):
        staff = (StaffProfile.query.filter(StaffProfile.organization_id == g.tenant.id,
                                           StaffProfile.department_id == dept.id, StaffProfile.status != "exited")
                 .order_by(StaffProfile.full_name).all())
    from app.models import Meeting, Task
    open_tasks = Task.query.filter(Task.organization_id == g.tenant.id, Task.department_id == dept.id,
                                   Task.status.in_(Task.OPEN)).count()
    upcoming = Meeting.query.filter(Meeting.organization_id == g.tenant.id, Meeting.department_id == dept.id,
                                    Meeting.status == "scheduled", Meeting.starts_at >= utcnow()).count()
    return render_template("people/department_detail.html", dept=dept, staff=staff, open_tasks=open_tasks,
                           upcoming=upcoming, action_form=ActionForm())


@departments_bp.route("/<int:dept_id>/toggle", methods=["POST"])
@require_permission("departments.manage")
def toggle(dept_id):
    dept = tenant_get_or_404(Department, dept_id)
    if ActionForm().validate_on_submit():
        dept.is_active = not dept.is_active
        audit.record("department.updated", f"Department {dept.name} {'reactivated' if dept.is_active else 'closed'}", entity=dept)
        db.session.commit()
    return redirect(url_for("departments.detail", dept_id=dept.id))


# ====================================================================================
# Staff
# ====================================================================================

def can_see_records(staff):
    if staff.user_id == current_user.id:
        return True
    return in_scope("staff.records", staff.department_id)


@staff_bp.route("/")
@require_permission("staff.view")
def index():
    q = (request.args.get("q") or "").strip()
    dept = request.args.get("department", type=int)
    status = request.args.get("status") or ""
    stmt = select(StaffProfile).where(StaffProfile.organization_id == g.tenant.id).order_by(StaffProfile.full_name)
    if status in StaffProfile.STATUSES:
        stmt = stmt.where(StaffProfile.status == status)
    else:
        stmt = stmt.where(StaffProfile.status != "exited")
    if dept:
        stmt = stmt.where(StaffProfile.department_id == dept)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(StaffProfile.full_name.ilike(like), StaffProfile.employee_number.ilike(like),
                              StaffProfile.position.ilike(like), StaffProfile.email.ilike(like)))
    page = db.paginate(stmt, page=page_arg(), per_page=30, error_out=False)
    return render_template("people/staff.html", page=page, q=q, dept=dept, status=status,
                           departments=department_choices("All departments", active_only=False),
                           statuses=StaffProfile.STATUSES)


def _linkable_users(current_user_id=None):
    taken = {s.user_id for s in StaffProfile.query.filter(StaffProfile.organization_id == g.tenant.id,
                                                          StaffProfile.user_id.isnot(None))}
    return [(0, "— No sign-in —")] + [(uid, name) for uid, name in member_choices()
                                      if uid not in taken or uid == current_user_id]


@staff_bp.route("/new", methods=["GET", "POST"])
@staff_bp.route("/<int:staff_id>/edit", methods=["GET", "POST"])
@require_permission("staff.manage")
def edit(staff_id=None):
    staff = tenant_get_or_404(StaffProfile, staff_id) if staff_id else None
    if staff and staff.status == "exited":
        flash("This person has exited. Their record is kept read-only.", "warning")
        return redirect(url_for("staff.detail", staff_id=staff.id))
    form = StaffForm(obj=staff)
    form.department_id.choices = department_choices()
    form.user_id.choices = _linkable_users(staff.user_id if staff else None)
    if form.validate_on_submit():
        clash = StaffProfile.query.filter(StaffProfile.organization_id == g.tenant.id,
                                          StaffProfile.employee_number == form.employee_number.data,
                                          StaffProfile.id != (staff.id if staff else 0)).first()
        if clash:
            form.employee_number.errors.append("Another staff member already has this number.")
        else:
            if form.department_id.data:
                tenant_get_or_404(Department, form.department_id.data)
            creating = staff is None
            if creating:
                staff = StaffProfile(organization_id=g.tenant.id)
                db.session.add(staff)
            old_dept, old_pos = staff.department_id, staff.position
            for f in ("full_name", "employee_number", "email", "phone", "position", "employment_type", "status",
                      "start_date", "contract_end_date", "work_location", "emergency_name", "emergency_phone",
                      "emergency_relationship", "notes", "department_id", "user_id"):
                val = getattr(form, f).data
                setattr(staff, f, val if val not in ("",) else None)
            staff.status = form.status.data
            db.session.flush()
            if not creating and old_dept != staff.department_id:
                db.session.add(StaffTransfer(organization_id=g.tenant.id, staff_id=staff.id, from_department_id=old_dept,
                                             to_department_id=staff.department_id, from_position=old_pos,
                                             to_position=staff.position, effective_date=date.today(),
                                             reason="Department changed on staff record", recorded_by_id=current_user.id))
            audit.record("staff.created" if creating else "staff.updated", f"Staff record {staff.employee_number} saved", entity=staff)
            db.session.commit()
            flash("Staff record saved.", "success")
            return redirect(url_for("staff.detail", staff_id=staff.id))
    return render_template("people/staff_form.html", form=form, staff=staff)


@staff_bp.route("/<int:staff_id>")
@require_permission("staff.view")
def detail(staff_id):
    staff = tenant_get_or_404(StaffProfile, staff_id)
    records = can_see_records(staff)
    ctx = {"staff": staff, "records": records, "manage": can("staff.manage") and staff.status != "exited"}
    if records:
        ctx.update(
            leave=LeaveRequest.query.filter_by(staff_id=staff.id).order_by(LeaveRequest.start_date.desc()).limit(20).all(),
            attendance=AttendanceRecord.query.filter(AttendanceRecord.staff_id == staff.id,
                                                     AttendanceRecord.date >= date.today() - timedelta(days=60))
            .order_by(AttendanceRecord.date.desc()).all(),
            training=TrainingRecord.query.filter_by(staff_id=staff.id).order_by(TrainingRecord.start_date.desc()).all(),
            reviews=PerformanceReview.query.filter_by(staff_id=staff.id).order_by(PerformanceReview.created_at.desc()).all(),
            transfers=StaffTransfer.query.filter_by(staff_id=staff.id).order_by(StaffTransfer.effective_date.desc()).all(),
            documents=Document.query.filter_by(organization_id=g.tenant.id, related_type="staff", related_id=staff.id)
            .order_by(Document.created_at.desc()).all(),
        )
    if ctx["manage"]:
        tf = TransferForm()
        tf.to_department_id.choices = department_choices()
        ctx.update(training_form=TrainingForm(), review_form=ReviewForm(), transfer_form=tf, exit_form=ExitForm())
    return render_template("people/staff_detail.html", **ctx)


def _staff_for_hr_post(staff_id):
    staff = tenant_get_or_404(StaffProfile, staff_id)
    if staff.status == "exited":
        abort(400)
    return staff


@staff_bp.route("/<int:staff_id>/training", methods=["POST"])
@require_permission("staff.manage")
def add_training(staff_id):
    staff = _staff_for_hr_post(staff_id)
    form = TrainingForm()
    if form.validate_on_submit():
        rec = TrainingRecord(organization_id=g.tenant.id, staff_id=staff.id)
        form.populate_obj(rec)
        db.session.add(rec)
        audit.record("staff.training_added", f"Training '{rec.title}' added for {staff.employee_number}", entity=staff)
        db.session.commit()
        flash("Training record added.", "success")
    else:
        flash("Check the training details.", "danger")
    return redirect(url_for("staff.detail", staff_id=staff.id) + "#training")


@staff_bp.route("/<int:staff_id>/review", methods=["POST"])
@require_permission("staff.manage")
def add_review(staff_id):
    staff = _staff_for_hr_post(staff_id)
    form = ReviewForm()
    if form.validate_on_submit():
        rec = PerformanceReview(organization_id=g.tenant.id, staff_id=staff.id, reviewer_id=current_user.id)
        form.populate_obj(rec)
        db.session.add(rec)
        audit.record("staff.review_added", f"Performance review {rec.period} added for {staff.employee_number}", entity=staff)
        db.session.commit()
        flash("Performance review saved.", "success")
    else:
        flash("Check the review details.", "danger")
    return redirect(url_for("staff.detail", staff_id=staff.id) + "#performance")


@staff_bp.route("/<int:staff_id>/transfer", methods=["POST"])
@require_permission("staff.manage")
def transfer(staff_id):
    staff = _staff_for_hr_post(staff_id)
    form = TransferForm()
    form.to_department_id.choices = department_choices()
    if form.validate_on_submit():
        if form.to_department_id.data:
            tenant_get_or_404(Department, form.to_department_id.data)
        db.session.add(StaffTransfer(organization_id=g.tenant.id, staff_id=staff.id,
                                     from_department_id=staff.department_id, to_department_id=form.to_department_id.data,
                                     from_position=staff.position, to_position=form.to_position.data or staff.position,
                                     effective_date=form.effective_date.data, reason=form.reason.data or None,
                                     recorded_by_id=current_user.id))
        staff.department_id = form.to_department_id.data
        staff.position = form.to_position.data or staff.position
        audit.record("staff.transferred", f"{staff.employee_number} transferred", entity=staff)
        db.session.commit()
        flash("Transfer recorded.", "success")
    else:
        flash("Check the transfer details.", "danger")
    return redirect(url_for("staff.detail", staff_id=staff.id) + "#transfers")


@staff_bp.route("/<int:staff_id>/exit", methods=["POST"])
@require_permission("staff.manage")
def record_exit(staff_id):
    staff = _staff_for_hr_post(staff_id)
    form = ExitForm()
    if form.validate_on_submit():
        staff.status = "exited"
        staff.exit_date, staff.exit_type = form.exit_date.data, form.exit_type.data
        staff.exit_reason = form.exit_reason.data or None
        staff.exit_clearance_done = form.exit_clearance_done.data
        if form.remove_access.data and staff.user_id and staff.user_id != current_user.id:
            m = Membership.query.filter_by(organization_id=g.tenant.id, user_id=staff.user_id).first()
            if m and not (m.role and m.role.is_admin):
                m.status = Membership.SUSPENDED
        audit.record("staff.exited", f"{staff.employee_number} exited ({staff.exit_type})", entity=staff)
        db.session.commit()
        flash("Exit recorded. The staff record is now read-only.", "success")
    else:
        flash("Check the exit details.", "danger")
    return redirect(url_for("staff.detail", staff_id=staff.id))


# ====================================================================================
# Leave
# ====================================================================================

def _year_used(staff_id, leave_type_id, year, include_pending=False):
    statuses = ("approved", "pending") if include_pending else ("approved",)
    return db.session.scalar(select(func.coalesce(func.sum(LeaveRequest.days), 0)).where(
        LeaveRequest.staff_id == staff_id, LeaveRequest.leave_type_id == leave_type_id,
        LeaveRequest.status.in_(statuses),
        LeaveRequest.start_date >= date(year, 1, 1), LeaveRequest.start_date <= date(year, 12, 31))) or 0


def _approvable_stmt():
    stmt = (select(LeaveRequest).join(StaffProfile, LeaveRequest.staff_id == StaffProfile.id)
            .where(LeaveRequest.organization_id == g.tenant.id))
    return scoped(stmt, "leave.approve", dept_col=StaffProfile.department_id)


@leave_bp.route("/")
@require_permission("leave.request")
def index():
    me = my_staff()
    mine = (LeaveRequest.query.filter_by(staff_id=me.id).order_by(LeaveRequest.start_date.desc()).limit(30).all()
            if me else [])
    balances = []
    if me:
        for lt in LeaveType.query.filter_by(organization_id=g.tenant.id, is_active=True).order_by(LeaveType.name):
            if lt.days_per_year:
                used = _year_used(me.id, lt.id, date.today().year)
                balances.append((lt, used, lt.days_per_year - used))
    pending = []
    if can("leave.approve"):
        pending = db.session.execute(_approvable_stmt().where(LeaveRequest.status == "pending")
                                     .order_by(LeaveRequest.start_date)).scalars().all()
    on_leave = []
    if can("staff.view"):
        today = date.today()
        on_leave = (LeaveRequest.query.filter(LeaveRequest.organization_id == g.tenant.id, LeaveRequest.status == "approved",
                                              LeaveRequest.end_date >= today, LeaveRequest.start_date <= today + timedelta(days=30))
                    .order_by(LeaveRequest.start_date).all())
    return render_template("people/leave.html", me=me, mine=mine, balances=balances, pending=pending,
                           on_leave=on_leave, decision_form=DecisionForm(), action_form=ActionForm(), today=date.today())


@leave_bp.route("/request", methods=["GET", "POST"])
@require_permission("leave.request")
def request_leave():
    me = my_staff()
    if me is None:
        flash("Your sign-in is not linked to a staff record yet. Ask HR to link it.", "warning")
        return redirect(url_for("leave.index"))
    form = LeaveRequestForm()
    form.leave_type_id.choices = [(t.id, t.name) for t in LeaveType.query.filter_by(
        organization_id=g.tenant.id, is_active=True).order_by(LeaveType.name)]
    if form.validate_on_submit():
        lt = tenant_get_or_404(LeaveType, form.leave_type_id.data)
        days = working_days(form.start_date.data, form.end_date.data)
        overlap = LeaveRequest.query.filter(LeaveRequest.staff_id == me.id, LeaveRequest.status.in_(("pending", "approved")),
                                            LeaveRequest.start_date <= form.end_date.data,
                                            LeaveRequest.end_date >= form.start_date.data).first()
        if days == 0:
            form.end_date.errors.append("These dates contain no working days.")
        elif overlap:
            form.start_date.errors.append("You already have leave requested or approved for some of these days.")
        elif lt.days_per_year and _year_used(me.id, lt.id, form.start_date.data.year, True) + days > lt.days_per_year:
            form.end_date.errors.append(f"This would exceed your {lt.days_per_year} days of {lt.name.lower()} for the year.")
        else:
            req = LeaveRequest(organization_id=g.tenant.id, staff_id=me.id, leave_type_id=lt.id,
                               start_date=form.start_date.data, end_date=form.end_date.data, days=days,
                               reason=form.reason.data or None, requested_by_id=current_user.id)
            db.session.add(req)
            db.session.flush()
            approvers = _leave_approvers(me)
            notify(approvers, "leave", f"Leave request from {me.full_name}",
                   f"{lt.name}: {req.start_date:%d %b} – {req.end_date:%d %b %Y} ({days} working days)", "leave.index")
            audit.record("leave.requested", f"{lt.name} {days} days requested", entity=req)
            db.session.commit()
            flash(f"Leave requested ({days} working days).", "success")
            return redirect(url_for("leave.index"))
    return render_template("people/leave_request.html", form=form)


def _leave_approvers(staff):
    """Members whose role can approve this staff member's leave."""
    from app.rbac import permissions_for_role
    out = []
    for m in Membership.query.filter_by(organization_id=g.tenant.id, status=Membership.ACTIVE).all():
        perms = permissions_for_role(m.role) if m.role else {}
        scope = perms.get("leave.approve")
        if scope == "organization":
            out.append(m.user_id)
        elif scope == "department" and staff.department_id:
            mine = StaffProfile.query.filter_by(organization_id=g.tenant.id, user_id=m.user_id).first()
            if mine and mine.department_id == staff.department_id:
                out.append(m.user_id)
    return [u for u in out if u != staff.user_id]


@leave_bp.route("/<int:req_id>/<action>", methods=["POST"])
@require_permission("leave.request")
def decide(req_id, action):
    req = tenant_get_or_404(LeaveRequest, req_id)
    form = DecisionForm()
    if not form.validate_on_submit():
        abort(400)
    if action == "cancel":
        me = my_staff()
        if not me or req.staff_id != me.id or req.status not in ("pending", "approved") or req.start_date <= date.today():
            abort(403)
        req.status = "cancelled"
    elif action in ("approve", "reject"):
        if not can("leave.approve") or not in_scope("leave.approve", req.staff.department_id):
            abort(403)
        if req.staff.user_id == current_user.id:
            flash("You cannot decide on your own leave.", "danger")
            return redirect(url_for("leave.index"))
        if req.status != "pending":
            flash("This request has already been decided.", "warning")
            return redirect(url_for("leave.index"))
        req.status = "approved" if action == "approve" else "rejected"
        req.decided_by_id, req.decided_at, req.decision_note = current_user.id, utcnow(), form.note.data or None
        notify([req.staff.user_id], "leave", f"Your leave was {req.status}",
               f"{req.leave_type.name}: {req.start_date:%d %b} – {req.end_date:%d %b %Y}. {req.decision_note or ''}",
               "leave.index")
    else:
        abort(404)
    audit.record(f"leave.{action}", f"Leave {req.status} for {req.staff.employee_number}", entity=req)
    db.session.commit()
    flash(f"Leave {req.status}.", "success")
    return redirect(url_for("leave.index"))


@leave_bp.route("/types", methods=["GET", "POST"])
@require_permission("leave.manage")
def types():
    form = LeaveTypeForm()
    if form.validate_on_submit():
        if LeaveType.query.filter_by(organization_id=g.tenant.id, name=form.name.data).first():
            form.name.errors.append("This leave type already exists.")
        else:
            lt = LeaveType(organization_id=g.tenant.id, name=form.name.data, days_per_year=form.days_per_year.data)
            db.session.add(lt)
            audit.record("leave.type_created", f"Leave type {lt.name} created")
            db.session.commit()
            flash("Leave type added.", "success")
            return redirect(url_for("leave.types"))
    rows = LeaveType.query.filter_by(organization_id=g.tenant.id).order_by(LeaveType.is_active.desc(), LeaveType.name).all()
    return render_template("people/leave_types.html", form=form, rows=rows, action_form=ActionForm())


@leave_bp.route("/types/<int:type_id>/toggle", methods=["POST"])
@require_permission("leave.manage")
def toggle_type(type_id):
    lt = tenant_get_or_404(LeaveType, type_id)
    if ActionForm().validate_on_submit():
        lt.is_active = not lt.is_active
        audit.record("leave.type_updated", f"Leave type {lt.name} {'enabled' if lt.is_active else 'disabled'}")
        db.session.commit()
    return redirect(url_for("leave.types"))


# ====================================================================================
# Attendance
# ====================================================================================

@attendance_bp.route("/", methods=["GET", "POST"])
@require_permission("attendance.record")
def register():
    try:
        day = datetime.strptime(request.values.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        day = date.today()
    if day > date.today():
        day = date.today()
    dept = request.values.get("department", type=int)
    stmt = (select(StaffProfile).where(StaffProfile.organization_id == g.tenant.id, StaffProfile.status != "exited")
            .order_by(StaffProfile.full_name))
    stmt = scoped(stmt, "attendance.record", dept_col=StaffProfile.department_id, own_cols=(StaffProfile.user_id,))
    if dept:
        stmt = stmt.where(StaffProfile.department_id == dept)
    people = db.session.execute(stmt).scalars().all()
    existing = {r.staff_id: r for r in AttendanceRecord.query.filter(
        AttendanceRecord.organization_id == g.tenant.id, AttendanceRecord.date == day,
        AttendanceRecord.staff_id.in_([p.id for p in people] or [0]))}
    on_leave = {r.staff_id for r in LeaveRequest.query.filter(
        LeaveRequest.organization_id == g.tenant.id, LeaveRequest.status == "approved",
        LeaveRequest.start_date <= day, LeaveRequest.end_date >= day)}
    form = ActionForm()
    if request.method == "POST":
        if not form.validate_on_submit():
            abort(400)
        valid = {c for c, _ in ATTENDANCE_CHOICES}
        saved = 0
        for p in people:
            status = request.form.get(f"status_{p.id}", "")
            note = (request.form.get(f"note_{p.id}", "") or "").strip()[:300] or None
            if status not in valid:
                continue
            rec = existing.get(p.id)
            if rec is None:
                rec = AttendanceRecord(organization_id=g.tenant.id, staff_id=p.id, date=day)
                db.session.add(rec)
            rec.status, rec.note, rec.recorded_by_id = status, note, current_user.id
            saved += 1
        audit.record("attendance.recorded", f"Attendance for {day:%d %b %Y}: {saved} people")
        db.session.commit()
        flash(f"Attendance saved for {saved} people.", "success")
        return redirect(url_for("attendance.register", date=day.isoformat(), department=dept or ""))
    return render_template("people/attendance.html", day=day, people=people, existing=existing, on_leave=on_leave,
                           choices=ATTENDANCE_CHOICES, form=form, dept=dept,
                           departments=department_choices("All departments in my scope"),
                           scope=scope_of("attendance.record"), my_dept=my_department_id())
