"""Programmes management (Phase 3).

Planning, results, finance and monitoring tables carry a ``programme_id``. They are
nullable on purpose: Phase 4 adds a ``project_id`` to the same tables so a project's
activities, indicators and budget use the same structures, whether or not the
project belongs to a programme.
"""
from .base import TenantMixin, TimestampMixin, db

MONEY = db.Numeric(14, 2)


# --- Organization-level registers -------------------------------------------------------

class Donor(TenantMixin, TimestampMixin, db.Model):
    """Donor or funding partner."""
    __tablename__ = "donors"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_donor_org_name"),)

    TYPES = ("Bilateral", "Multilateral", "Foundation", "Government", "Corporate", "Individual", "Internal", "Other")

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    donor_type = db.Column(db.String(40))
    contact_name = db.Column(db.String(200))
    contact_email = db.Column(db.String(255))
    notes = db.Column(db.Text)


class Location(TenantMixin, TimestampMixin, db.Model):
    """Places where work happens (communities, districts, sites)."""
    __tablename__ = "locations"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", "district", name="uq_location_org_name_district"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    district = db.Column(db.String(120))
    region = db.Column(db.String(120))
    country = db.Column(db.String(80))
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def label(self):
        return ", ".join(p for p in (self.name, self.district, self.region) if p)


class BudgetCategory(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "budget_categories"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_budgetcat_org_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)


# --- Programme ---------------------------------------------------------------------------

class Programme(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "programmes"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_programme_org_code"),)

    STATUSES = ("draft", "planned", "approved", "active", "on_hold", "completed", "closed", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    background = db.Column(db.Text)
    rationale = db.Column(db.Text)
    goal = db.Column(db.Text)
    sector = db.Column(db.String(120), index=True)
    target_population = db.Column(db.Text)
    geographic_coverage = db.Column(db.Text)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    manager_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    currency = db.Column(db.String(3), nullable=False, default="GHS")
    approved_budget = db.Column(MONEY, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    status_note = db.Column(db.String(500))
    # Planning narrative
    strategy = db.Column(db.Text)
    implementation_plan = db.Column(db.Text)
    theory_of_change = db.Column(db.Text)
    assumptions = db.Column(db.Text)
    risks_summary = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))

    manager = db.relationship("User", foreign_keys=[manager_id])
    department = db.relationship("Department")
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    team = db.relationship("ProgrammeTeamMember", cascade="all, delete-orphan", lazy="selectin",
                           back_populates="programme")

    @property
    def duration_months(self):
        if not (self.start_date and self.end_date):
            return None
        months = (self.end_date.year - self.start_date.year) * 12 + self.end_date.month - self.start_date.month
        return months + (1 if self.end_date.day >= self.start_date.day else 0)

    kind = "programme"
    fk = "programme_id"
    perm = "programmes"
    ref_prefix = "PRG"

    def member_ids(self):
        return {self.manager_id} | {t.user_id for t in self.team} - {None}


class ProgrammeTeamMember(TenantMixin, db.Model):
    __tablename__ = "programme_team"
    __table_args__ = (db.UniqueConstraint("programme_id", "user_id", name="uq_progteam_prog_user"),)

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_label = db.Column(db.String(100))

    programme = db.relationship("Programme", back_populates="team")
    user = db.relationship("User")


# --- Results framework and indicators -----------------------------------------------------------

class ResultNode(TenantMixin, TimestampMixin, db.Model):
    """One statement in the results framework / logical framework."""
    __tablename__ = "result_nodes"

    LEVELS = {"goal": "Goal / impact", "objective": "Objective", "outcome": "Outcome", "output": "Output"}
    ORDER = ("goal", "objective", "outcome", "output")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey("result_nodes.id", ondelete="CASCADE"), index=True)
    level = db.Column(db.String(20), nullable=False)
    code = db.Column(db.String(20))
    statement = db.Column(db.Text, nullable=False)
    assumptions = db.Column(db.Text)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    parent = db.relationship("ResultNode", remote_side=[id])


class Indicator(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "indicators"

    AGGREGATIONS = {"sum": "Add up each period's results (e.g. people trained)",
                    "latest": "Use the most recent result (e.g. a percentage or rate)",
                    "max": "Use the highest result reached"}
    FREQUENCIES = ("monthly", "quarterly", "semi_annual", "annual", "end_of_programme")
    DISAGGREGATIONS = {"sex": ("Female", "Male"),
                       "age": ("Under 18", "18–35", "36–59", "60 and over"),
                       "disability": ("With disability", "Without disability")}

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    result_id = db.Column(db.Integer, db.ForeignKey("result_nodes.id", ondelete="SET NULL"), index=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(400), nullable=False)
    definition = db.Column(db.Text)
    unit = db.Column(db.String(40), nullable=False, default="number")  # number, percent, currency, text-free
    aggregation = db.Column(db.String(10), nullable=False, default="sum")
    direction = db.Column(db.String(10), nullable=False, default="increase")
    baseline_value = db.Column(db.Numeric(16, 4))
    baseline_date = db.Column(db.Date)
    target_value = db.Column(db.Numeric(16, 4))
    means_of_verification = db.Column(db.Text)
    data_source = db.Column(db.String(300))
    frequency = db.Column(db.String(20), nullable=False, default="quarterly")
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    disaggregations = db.Column(db.JSON)  # e.g. ["sex", "age"]
    # A project indicator can feed a programme indicator; each result is still stored once.
    contributes_to_id = db.Column(db.Integer, db.ForeignKey("indicators.id", ondelete="SET NULL"), index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    result = db.relationship("ResultNode")
    responsible = db.relationship("User")
    contributes_to = db.relationship("Indicator", remote_side=[id])
    targets = db.relationship("IndicatorTarget", cascade="all, delete-orphan", order_by="IndicatorTarget.period_start")
    results = db.relationship("IndicatorResult", cascade="all, delete-orphan",
                              order_by="IndicatorResult.period_end.desc()")


class IndicatorTarget(TenantMixin, db.Model):
    __tablename__ = "indicator_targets"

    id = db.Column(db.Integer, primary_key=True)
    indicator_id = db.Column(db.Integer, db.ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False, index=True)
    period_label = db.Column(db.String(40), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    target_value = db.Column(db.Numeric(16, 4), nullable=False)


class IndicatorResult(TenantMixin, TimestampMixin, db.Model):
    """An actual achievement reported for a period, optionally disaggregated."""
    __tablename__ = "indicator_results"

    STATUSES = ("submitted", "verified", "rejected")

    id = db.Column(db.Integer, primary_key=True)
    indicator_id = db.Column(db.Integer, db.ForeignKey("indicators.id", ondelete="CASCADE"), nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False, index=True)
    value = db.Column(db.Numeric(16, 4), nullable=False)
    breakdown = db.Column(db.JSON)  # {"sex": {"Female": 12, "Male": 9}, ...}
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    source = db.Column(db.String(300))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="submitted", index=True)
    reported_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    verified_at = db.Column(db.DateTime(timezone=True))
    review_note = db.Column(db.String(500))

    indicator = db.relationship("Indicator", back_populates="results")
    location = db.relationship("Location")
    reported_by = db.relationship("User", foreign_keys=[reported_by_id])
    verified_by = db.relationship("User", foreign_keys=[verified_by_id])


# --- Planning and implementation ------------------------------------------------------------------

class Workplan(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "workplans"

    PERIODS = {"annual": "Annual", "quarterly": "Quarterly", "monthly": "Monthly"}

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title = db.Column(db.String(200), nullable=False)
    period_type = db.Column(db.String(20), nullable=False, default="annual")
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="draft")  # draft / approved
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))

    approved_by = db.relationship("User")


class Activity(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "activities"

    STATUSES = ("planned", "in_progress", "completed", "postponed", "cancelled")
    OPEN = ("planned", "in_progress", "postponed")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    workplan_id = db.Column(db.Integer, db.ForeignKey("workplans.id", ondelete="SET NULL"), index=True)
    result_id = db.Column(db.Integer, db.ForeignKey("result_nodes.id", ondelete="SET NULL"), index=True)
    budget_line_id = db.Column(db.Integer, db.ForeignKey("budget_lines.id", ondelete="SET NULL"), index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    component_id = db.Column(db.Integer, db.ForeignKey("project_components.id", ondelete="SET NULL"), index=True)
    code = db.Column(db.String(20))
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))
    planned_start = db.Column(db.Date, index=True)
    planned_end = db.Column(db.Date, index=True)
    actual_start = db.Column(db.Date)
    actual_end = db.Column(db.Date)
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    planned_budget = db.Column(MONEY, nullable=False, default=0)
    target_participants = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="planned", index=True)
    progress = db.Column(db.Integer, nullable=False, default=0)  # 0–100
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    workplan = db.relationship("Workplan")
    component = db.relationship("Component")
    programme = db.relationship("Programme")
    project = db.relationship("Project")
    result = db.relationship("ResultNode")
    budget_line = db.relationship("BudgetLine")
    location = db.relationship("Location")
    responsible = db.relationship("User")
    reports = db.relationship("ActivityReport", cascade="all, delete-orphan", order_by="ActivityReport.report_date.desc()")


class ActivityReport(TenantMixin, TimestampMixin, db.Model):
    """What happened when an activity (or one session of it) was carried out."""
    __tablename__ = "activity_reports"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="CASCADE"), nullable=False, index=True)
    report_date = db.Column(db.Date, nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    participants_female = db.Column(db.Integer, nullable=False, default=0)
    participants_male = db.Column(db.Integer, nullable=False, default=0)
    participants_youth = db.Column(db.Integer)          # of which aged 15–35
    participants_disability = db.Column(db.Integer)     # of which with a disability
    summary = db.Column(db.Text, nullable=False)
    challenges = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="submitted")  # submitted / approved
    submitted_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    activity = db.relationship("Activity", back_populates="reports")
    location = db.relationship("Location")
    submitted_by = db.relationship("User", foreign_keys=[submitted_by_id])

    @property
    def participants_total(self):
        return (self.participants_female or 0) + (self.participants_male or 0)


class Milestone(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "milestones"

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title = db.Column(db.String(250), nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    achieved_date = db.Column(db.Date)
    notes = db.Column(db.Text)
    reminder_sent_at = db.Column(db.DateTime(timezone=True))


# --- Finance ------------------------------------------------------------------------------------------

class BudgetLine(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "budget_lines"

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("budget_categories.id", ondelete="RESTRICT"), nullable=False)
    code = db.Column(db.String(30))
    description = db.Column(db.String(300), nullable=False)
    amount = db.Column(MONEY, nullable=False, default=0)  # current approved amount (after revisions)
    original_amount = db.Column(MONEY, nullable=False, default=0)

    category = db.relationship("BudgetCategory")


class BudgetRevision(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "budget_revisions"

    STATUSES = ("pending", "approved", "rejected")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decided_at = db.Column(db.DateTime(timezone=True))
    decision_note = db.Column(db.String(500))

    lines = db.relationship("BudgetRevisionLine", cascade="all, delete-orphan")
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])


class BudgetRevisionLine(TenantMixin, db.Model):
    __tablename__ = "budget_revision_lines"

    id = db.Column(db.Integer, primary_key=True)
    revision_id = db.Column(db.Integer, db.ForeignKey("budget_revisions.id", ondelete="CASCADE"), nullable=False, index=True)
    budget_line_id = db.Column(db.Integer, db.ForeignKey("budget_lines.id", ondelete="CASCADE"), nullable=False)
    old_amount = db.Column(MONEY, nullable=False)
    new_amount = db.Column(MONEY, nullable=False)

    budget_line = db.relationship("BudgetLine")


class FundingAgreement(TenantMixin, TimestampMixin, db.Model):
    """A funding commitment from a donor (grant agreement, pledge)."""
    __tablename__ = "funding_agreements"

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id", ondelete="RESTRICT"), nullable=False, index=True)
    reference = db.Column(db.String(120))
    committed_amount = db.Column(MONEY, nullable=False)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    reporting_requirements = db.Column(db.Text)

    donor = db.relationship("Donor")
    receipts = db.relationship("FundingReceipt", cascade="all, delete-orphan", order_by="FundingReceipt.received_on")


class FundingReceipt(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "funding_receipts"

    id = db.Column(db.Integer, primary_key=True)
    agreement_id = db.Column(db.Integer, db.ForeignKey("funding_agreements.id", ondelete="CASCADE"), nullable=False, index=True)
    received_on = db.Column(db.Date, nullable=False)
    amount = db.Column(MONEY, nullable=False)
    reference = db.Column(db.String(120))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))


class Expenditure(TenantMixin, TimestampMixin, db.Model):
    """Money spent (expenditure) or reserved but not yet paid (commitment)."""
    __tablename__ = "expenditures"

    KINDS = {"expenditure": "Expenditure", "commitment": "Commitment"}
    STATUSES = ("pending", "approved", "rejected", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    budget_line_id = db.Column(db.Integer, db.ForeignKey("budget_lines.id", ondelete="RESTRICT"), nullable=False, index=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    kind = db.Column(db.String(20), nullable=False, default="expenditure")
    spent_on = db.Column(db.Date, nullable=False, index=True)
    description = db.Column(db.String(300), nullable=False)
    payee = db.Column(db.String(200))
    reference = db.Column(db.String(120))
    amount = db.Column(MONEY, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    decision_note = db.Column(db.String(500))
    # Phase 6: a payment against a purchase order (or the order's commitment)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id", ondelete="SET NULL", use_alter=True,
                                                            name="fk_expenditures_purchase_order_id"), index=True)

    budget_line = db.relationship("BudgetLine")
    activity = db.relationship("Activity")
    purchase_order = db.relationship("PurchaseOrder", foreign_keys=[purchase_order_id])
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])


# --- Monitoring, evaluation and learning --------------------------------------------------------------

class MonitoringVisit(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "monitoring_visits"

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    visit_date = db.Column(db.Date, nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    purpose = db.Column(db.String(300), nullable=False)
    findings = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    follow_up = db.Column(db.Text)
    visited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    location = db.relationship("Location")
    visited_by = db.relationship("User")


class Evaluation(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "evaluations"

    TYPES = ("Baseline", "Mid-term", "Final", "Ex-post", "Special study")
    STATUSES = ("planned", "ongoing", "completed")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    eval_type = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    evaluator = db.Column(db.String(200))
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="planned")
    findings = db.Column(db.Text)
    recommendations = db.Column(db.Text)


class LearningItem(TenantMixin, TimestampMixin, db.Model):
    """A lesson learned or recommendation, with the management response."""
    __tablename__ = "learning_items"

    KINDS = {"lesson": "Lesson learned", "recommendation": "Recommendation"}
    RESPONSE_STATUSES = ("open", "accepted", "partially_accepted", "not_accepted", "implemented")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("evaluations.id", ondelete="SET NULL"))
    kind = db.Column(db.String(20), nullable=False, default="lesson")
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    management_response = db.Column(db.Text)
    response_status = db.Column(db.String(30), nullable=False, default="open")
    responsible_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    due_date = db.Column(db.Date)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    evaluation = db.relationship("Evaluation")
    responsible = db.relationship("User", foreign_keys=[responsible_id])


# --- Reports -------------------------------------------------------------------------------------------

class ProgrammeReport(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "programme_reports"

    TYPES = {"monthly": "Monthly report", "quarterly": "Quarterly report", "semi_annual": "Semi-annual report",
             "annual": "Annual report", "donor": "Donor report", "performance": "Performance report"}
    STATUSES = ("draft", "submitted", "approved")

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    report_type = db.Column(db.String(20), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id", ondelete="SET NULL"))
    summary = db.Column(db.Text)
    achievements = db.Column(db.Text)
    challenges = db.Column(db.Text)
    lessons = db.Column(db.Text)
    next_steps = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="draft")
    due_date = db.Column(db.Date)
    snapshot = db.Column(db.JSON)  # figures frozen at approval, so approved reports never change
    prepared_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))

    donor = db.relationship("Donor")
    prepared_by = db.relationship("User", foreign_keys=[prepared_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])

