"""Departments, staff and HR records (Phase 2)."""
from .base import TenantMixin, TimestampMixin, db


class Department(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "departments"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_department_org_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    code = db.Column(db.String(20))
    description = db.Column(db.Text)
    responsibilities = db.Column(db.Text)
    head_staff_id = db.Column(db.Integer, db.ForeignKey("staff_profiles.id", ondelete="SET NULL", use_alter=True))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    head = db.relationship("StaffProfile", foreign_keys=[head_staff_id], post_update=True)


class StaffProfile(TenantMixin, TimestampMixin, db.Model):
    """A member of staff. May or may not have a ZENTAVA OIMS sign-in (user_id)."""

    __tablename__ = "staff_profiles"
    __table_args__ = (
        db.UniqueConstraint("organization_id", "employee_number", name="uq_staff_org_empno"),
        db.UniqueConstraint("organization_id", "user_id", name="uq_staff_org_user"),
    )

    STATUSES = ("active", "probation", "on_leave", "suspended", "exited")
    TYPES = ("Permanent", "Fixed-term contract", "Part-time", "Consultant", "National service", "Intern", "Volunteer")
    EXIT_TYPES = ("Resignation", "End of contract", "Retirement", "Dismissal", "Redundancy", "Death", "Other")

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    employee_number = db.Column(db.String(40), nullable=False)
    full_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(255))
    phone = db.Column(db.String(50))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    position = db.Column(db.String(150))
    employment_type = db.Column(db.String(40))
    status = db.Column(db.String(20), nullable=False, default="active", index=True)
    start_date = db.Column(db.Date)
    contract_end_date = db.Column(db.Date)
    work_location = db.Column(db.String(150))
    emergency_name = db.Column(db.String(200))
    emergency_phone = db.Column(db.String(50))
    emergency_relationship = db.Column(db.String(80))
    notes = db.Column(db.Text)
    exit_date = db.Column(db.Date)
    exit_type = db.Column(db.String(40))
    exit_reason = db.Column(db.Text)
    exit_clearance_done = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User")
    department = db.relationship("Department", foreign_keys=[department_id])


class LeaveType(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "leave_types"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_leavetype_org_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    days_per_year = db.Column(db.Integer)  # NULL = no fixed entitlement
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class LeaveRequest(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "leave_requests"

    STATUSES = ("pending", "approved", "rejected", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    leave_type_id = db.Column(db.Integer, db.ForeignKey("leave_types.id", ondelete="RESTRICT"), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decided_at = db.Column(db.DateTime(timezone=True))
    decision_note = db.Column(db.String(500))

    staff = db.relationship("StaffProfile")
    leave_type = db.relationship("LeaveType")
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])


class AttendanceRecord(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "attendance_records"
    __table_args__ = (db.UniqueConstraint("staff_id", "date", name="uq_attendance_staff_date"),)

    STATUSES = ("present", "late", "absent", "remote", "on_leave", "field_work")

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)
    note = db.Column(db.String(300))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    staff = db.relationship("StaffProfile")


class TrainingRecord(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "training_records"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    provider = db.Column(db.String(200))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    outcome = db.Column(db.String(300))


class PerformanceReview(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "performance_reviews"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    period = db.Column(db.String(60), nullable=False)
    rating = db.Column(db.Integer)  # 1–5
    summary = db.Column(db.Text)
    goals = db.Column(db.Text)
    reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    reviewer = db.relationship("User")


class StaffTransfer(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "staff_transfers"

    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer, db.ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False, index=True)
    from_department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"))
    to_department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"))
    from_position = db.Column(db.String(150))
    to_position = db.Column(db.String(150))
    effective_date = db.Column(db.Date, nullable=False)
    reason = db.Column(db.String(500))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    from_department = db.relationship("Department", foreign_keys=[from_department_id])
    to_department = db.relationship("Department", foreign_keys=[to_department_id])
