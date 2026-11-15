"""Project management (Phase 4).

A project uses the same planning, results, finance, monitoring and reporting tables as a
programme (through ``project_id``), and adds the work breakdown structure, deliverables,
risk and issue registers and closure. A project may belong to a programme or stand alone.
"""
from .base import TenantMixin, TimestampMixin, db
from .programmes import MONEY


class Project(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "projects"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_project_org_code"),)

    STATUSES = ("draft", "planned", "approved", "active", "on_hold", "completed", "closed", "cancelled")

    kind = "project"
    fk = "project_id"
    perm = "projects"
    ref_prefix = "PRJ"

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="SET NULL"), index=True)
    code = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    background = db.Column(db.Text)
    rationale = db.Column(db.Text)          # justification
    goal = db.Column(db.Text)
    objectives = db.Column(db.Text)
    expected_outcomes = db.Column(db.Text)
    expected_outputs = db.Column(db.Text)
    sector = db.Column(db.String(120), index=True)
    target_population = db.Column(db.Text)
    geographic_coverage = db.Column(db.Text)  # project location(s)
    funding_source = db.Column(db.String(200))
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id", ondelete="SET NULL"))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    currency = db.Column(db.String(3), nullable=False, default="GHS")
    approved_budget = db.Column(MONEY, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    status_note = db.Column(db.String(500))
    strategy = db.Column(db.Text)
    implementation_plan = db.Column(db.Text)
    theory_of_change = db.Column(db.Text)
    assumptions = db.Column(db.Text)
    risks_summary = db.Column(db.Text)
    proposal_summary = db.Column(db.Text)
    resource_plan = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    closed_at = db.Column(db.DateTime(timezone=True))

    programme = db.relationship("Programme", backref="projects")
    donor = db.relationship("Donor")
    manager = db.relationship("User", foreign_keys=[manager_id])
    department = db.relationship("Department")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    team = db.relationship("ProjectTeamMember", cascade="all, delete-orphan", lazy="selectin", back_populates="project")

    @property
    def duration_months(self):
        if not (self.start_date and self.end_date):
            return None
        months = (self.end_date.year - self.start_date.year) * 12 + self.end_date.month - self.start_date.month
        return months + (1 if self.end_date.day >= self.start_date.day else 0)

    def member_ids(self):
        return {self.manager_id} | {t.user_id for t in self.team} - {None}


class ProjectTeamMember(TenantMixin, db.Model):
    __tablename__ = "project_team"
    __table_args__ = (db.UniqueConstraint("project_id", "user_id", name="uq_projteam_proj_user"),)

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_label = db.Column(db.String(100))

    project = db.relationship("Project", back_populates="team")
    user = db.relationship("User")


class Component(TenantMixin, TimestampMixin, db.Model):
    """Top level of the work breakdown structure."""
    __tablename__ = "project_components"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    code = db.Column(db.String(20))
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    responsible = db.relationship("User")


class Deliverable(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "deliverables"

    STATUSES = ("pending", "submitted", "verified", "rejected", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    component_id = db.Column(db.Integer, db.ForeignKey("project_components.id", ondelete="SET NULL"), index=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    acceptance_criteria = db.Column(db.Text)
    due_date = db.Column(db.Date, index=True)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    priority = db.Column(db.String(10), nullable=False, default="normal")
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at = db.Column(db.DateTime(timezone=True))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    verified_at = db.Column(db.DateTime(timezone=True))
    review_note = db.Column(db.String(500))
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    component = db.relationship("Component")
    activity = db.relationship("Activity")
    responsible = db.relationship("User", foreign_keys=[responsible_id])
    submitted_by = db.relationship("User", foreign_keys=[submitted_by_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])


class RiskItem(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "risks"

    CATEGORIES = ("Operational", "Financial", "Security", "Safeguarding", "Political / external", "Environmental",
                  "Reputational", "Partner / delivery", "Legal / compliance", "Other")
    STATUSES = ("open", "monitoring", "closed")
    LIKELIHOOD = {1: "Rare", 2: "Unlikely", 3: "Possible", 4: "Likely", 5: "Almost certain"}
    IMPACT = {1: "Minimal", 2: "Minor", 3: "Moderate", 4: "Major", 5: "Severe"}

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    code = db.Column(db.String(20))
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(40), nullable=False, default="Operational")
    probability = db.Column(db.Integer, nullable=False, default=3)
    impact = db.Column(db.Integer, nullable=False, default=3)
    mitigation = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    review_date = db.Column(db.Date, index=True)
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    owner = db.relationship("User")

    @property
    def rating(self):
        return (self.probability or 0) * (self.impact or 0)

    @property
    def level(self):
        r = self.rating
        return "critical" if r >= 20 else "high" if r >= 12 else "medium" if r >= 6 else "low"


class Issue(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "project_issues"

    SEVERITIES = ("low", "medium", "high", "critical")
    STATUSES = ("open", "in_progress", "resolved", "closed")
    OPEN = ("open", "in_progress")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    risk_id = db.Column(db.Integer, db.ForeignKey("risks.id", ondelete="SET NULL"))
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    severity = db.Column(db.String(10), nullable=False, default="medium")
    status = db.Column(db.String(20), nullable=False, default="open", index=True)
    raised_on = db.Column(db.Date, nullable=False)
    raised_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    resolution = db.Column(db.Text)
    resolved_on = db.Column(db.Date)

    risk = db.relationship("RiskItem")
    raised_by = db.relationship("User", foreign_keys=[raised_by_id])
    owner = db.relationship("User", foreign_keys=[owner_id])


class ProjectClosure(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "project_closures"

    STATUSES = ("draft", "submitted", "approved", "returned")

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True)
    final_report = db.Column(db.Text)
    achievements = db.Column(db.Text)
    financial_reconciliation = db.Column(db.Text)
    lessons_learned = db.Column(db.Text)
    evaluation_summary = db.Column(db.Text)
    outstanding_issues = db.Column(db.Text)
    asset_handover = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="draft")
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    submitted_at = db.Column(db.DateTime(timezone=True))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    decision_note = db.Column(db.String(500))
    checklist_snapshot = db.Column(db.JSON)

    submitted_by = db.relationship("User", foreign_keys=[submitted_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
