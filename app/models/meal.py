"""MEAL & beneficiaries (Phase 5).

Beneficiaries are registered once per organization and enrolled in any number of programmes or
projects, so people reached can be counted without counting anyone twice. Contact details and ID
numbers are stored encrypted (app/crypto.py). Consent is recorded and can be withdrawn; a withdrawn
or exited person's record can be anonymized while keeping the numbers.
"""
from datetime import date

from .base import TenantMixin, TimestampMixin, db

AGE_BANDS = (("0-5", 0, 5), ("6-14", 6, 14), ("15-17", 15, 17), ("18-35", 18, 35), ("36-59", 36, 59),
             ("60+", 60, 200))
SEXES = {"female": "Female", "male": "Male", "other": "Other", "not_stated": "Not stated"}


def age_from(date_of_birth, birth_year, today=None):
    today = today or date.today()
    if date_of_birth:
        d = date_of_birth
        return today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    return today.year - birth_year if birth_year else None


def age_band(age):
    if age is None:
        return "Unknown"
    for label, lo, hi in AGE_BANDS:
        if lo <= age <= hi:
            return label
    return "Unknown"


class Household(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "households"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_household_org_code"),)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"), index=True)
    community = db.Column(db.String(200))
    head_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="SET NULL", use_alter=True,
                                                  name="fk_households_head_id_beneficiaries"))
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    location = db.relationship("Location")
    head = db.relationship("Beneficiary", foreign_keys=[head_id], post_update=True)
    members = db.relationship("Beneficiary", foreign_keys="Beneficiary.household_id", back_populates="household",
                              order_by="Beneficiary.code")


class Beneficiary(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "beneficiaries"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_beneficiary_org_code"),)

    STATUSES = ("active", "inactive", "exited", "merged")
    VULNERABILITIES = ("Female-headed household", "Child-headed household", "Orphan or vulnerable child",
                       "Person with disability", "Older person living alone", "Pregnant or breastfeeding",
                       "Displaced person", "Chronic illness", "Extreme poverty", "Survivor of violence")
    ID_TYPES = ("Ghana Card", "Voter ID", "Birth certificate", "NHIS card", "Passport", "School ID", "Other")
    RELATIONSHIPS = ("Head", "Spouse / partner", "Child", "Grandchild", "Parent", "Other relative", "Not related")

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    first_name = db.Column(db.String(120), nullable=False)
    last_name = db.Column(db.String(120), nullable=False)
    other_names = db.Column(db.String(120))
    sex = db.Column(db.String(12), nullable=False, default="not_stated", index=True)
    date_of_birth = db.Column(db.Date)                 # sensitive; exact date
    birth_year = db.Column(db.Integer, index=True)     # kept for age statistics (also after anonymizing)
    disability = db.Column(db.Boolean)
    disability_type = db.Column(db.String(200))        # sensitive
    household_id = db.Column(db.Integer, db.ForeignKey("households.id", ondelete="SET NULL"), index=True)
    relationship_to_head = db.Column(db.String(40))
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"), index=True)
    community = db.Column(db.String(200))
    phone_enc = db.Column(db.Text)
    phone_index = db.Column(db.String(64), index=True)
    id_type = db.Column(db.String(40))
    id_number_enc = db.Column(db.Text)
    id_number_index = db.Column(db.String(64), index=True)
    vulnerabilities = db.Column(db.JSON)               # sensitive
    notes = db.Column(db.Text)                         # sensitive
    status = db.Column(db.String(12), nullable=False, default="active", index=True)
    exit_reason = db.Column(db.String(300))
    merged_into_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="SET NULL"))
    registered_on = db.Column(db.Date, nullable=False, default=date.today)
    registered_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    anonymized_at = db.Column(db.DateTime(timezone=True))

    household = db.relationship("Household", foreign_keys=[household_id], back_populates="members")
    location = db.relationship("Location")
    registered_by = db.relationship("User")
    merged_into = db.relationship("Beneficiary", remote_side=[id])
    consents = db.relationship("ConsentRecord", back_populates="beneficiary", cascade="all, delete-orphan",
                               order_by="ConsentRecord.given_on.desc(), ConsentRecord.id.desc()")
    enrollments = db.relationship("Enrollment", back_populates="beneficiary", cascade="all, delete-orphan",
                                  order_by="Enrollment.enrolled_on")

    @property
    def full_name(self):
        return " ".join(p for p in (self.first_name, self.other_names, self.last_name) if p)

    @property
    def age(self):
        return age_from(self.date_of_birth, self.birth_year)

    @property
    def age_band(self):
        return age_band(self.age)

    @property
    def is_minor(self):
        return self.age is not None and self.age < 18

    @property
    def current_consent(self):
        """The most recent consent, if it has not been withdrawn."""
        for c in self.consents:
            return None if c.withdrawn_on else c
        return None

    @property
    def consent_state(self):
        if not self.consents:
            return "none"
        return "withdrawn" if self.consents[0].withdrawn_on else "given"


class ConsentRecord(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "consent_records"

    PURPOSES = {"services": "Registration and receiving services",
                "followup": "Being contacted for follow-up and surveys",
                "sharing": "Sharing anonymised data with donors and partners",
                "media": "Photos, stories or case studies"}
    GIVERS = {"self": "The person themself", "guardian": "Parent or guardian", "caregiver": "Caregiver"}
    METHODS = {"written": "Signed form", "thumbprint": "Thumbprint", "verbal": "Verbal, witnessed",
               "digital": "Digital / tablet"}

    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="CASCADE"), nullable=False,
                               index=True)
    given_on = db.Column(db.Date, nullable=False)
    given_by = db.Column(db.String(12), nullable=False, default="self")
    guardian_name = db.Column(db.String(200))
    purposes = db.Column(db.JSON, nullable=False, default=list)
    method = db.Column(db.String(12), nullable=False, default="written")
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    withdrawn_on = db.Column(db.Date)
    withdrawal_note = db.Column(db.String(500))

    beneficiary = db.relationship("Beneficiary", back_populates="consents")
    recorded_by = db.relationship("User")


class Enrollment(TenantMixin, TimestampMixin, db.Model):
    """A beneficiary taking part in one programme or one project."""
    __tablename__ = "enrollments"
    __table_args__ = (db.UniqueConstraint("beneficiary_id", "programme_id", name="uq_enrollment_ben_prog"),
                      db.UniqueConstraint("beneficiary_id", "project_id", name="uq_enrollment_ben_proj"))

    STATUSES = ("active", "completed", "exited")

    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="CASCADE"), nullable=False,
                               index=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    enrolled_on = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(12), nullable=False, default="active")
    ended_on = db.Column(db.Date)
    end_reason = db.Column(db.String(300))
    enrolled_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    beneficiary = db.relationship("Beneficiary", back_populates="enrollments")
    programme = db.relationship("Programme")
    project = db.relationship("Project")

    @property
    def owner(self):
        return self.project or self.programme


class ServiceRecord(TenantMixin, TimestampMixin, db.Model):
    """Something a beneficiary received: a kit, a training session, cash, a referral…"""
    __tablename__ = "service_records"

    id = db.Column(db.Integer, primary_key=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="CASCADE"), nullable=False,
                               index=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"), index=True)
    service_type = db.Column(db.String(120), nullable=False)
    delivered_on = db.Column(db.Date, nullable=False, index=True)
    quantity = db.Column(db.Numeric(14, 2))
    unit = db.Column(db.String(40))
    notes = db.Column(db.String(500))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    beneficiary = db.relationship("Beneficiary")
    activity = db.relationship("Activity")
    recorded_by = db.relationship("User")
    programme = db.relationship("Programme")
    project = db.relationship("Project")

    @property
    def owner(self):
        return self.project or self.programme


class ActivityAttendance(TenantMixin, db.Model):
    """Named attendance: who took part in one activity session (activity report)."""
    __tablename__ = "activity_attendance"
    __table_args__ = (db.UniqueConstraint("report_id", "beneficiary_id", name="uq_attendance_report_ben"),)

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey("activity_reports.id", ondelete="CASCADE"), nullable=False,
                          index=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="CASCADE"), nullable=False,
                               index=True)
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    beneficiary = db.relationship("Beneficiary")


# --- Data collection ----------------------------------------------------------------------

class DataForm(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "data_forms"

    STATUSES = ("draft", "published", "closed")
    LINKS = {"none": "Not about a registered person", "optional": "May be linked to a beneficiary",
             "required": "Must be linked to a beneficiary"}

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    beneficiary_link = db.Column(db.String(10), nullable=False, default="none")
    status = db.Column(db.String(12), nullable=False, default="draft", index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    published_at = db.Column(db.DateTime(timezone=True))

    programme = db.relationship("Programme")
    project = db.relationship("Project")
    fields = db.relationship("FormField", back_populates="form", cascade="all, delete-orphan",
                             order_by="FormField.sort_order, FormField.id")

    @property
    def owner(self):
        return self.project or self.programme


class FormField(TenantMixin, db.Model):
    __tablename__ = "form_fields"

    TYPES = {"text": "Short text", "long_text": "Long text", "number": "Number", "integer": "Whole number",
             "date": "Date", "choice": "One choice", "multi": "Several choices", "yes_no": "Yes / no"}

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("data_forms.id", ondelete="CASCADE"), nullable=False, index=True)
    key = db.Column(db.String(60), nullable=False)
    label = db.Column(db.String(300), nullable=False)
    help_text = db.Column(db.String(300))
    field_type = db.Column(db.String(12), nullable=False, default="text")
    options = db.Column(db.JSON)
    required = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    form = db.relationship("DataForm", back_populates="fields")


class FormSubmission(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "form_submissions"

    STATUSES = ("submitted", "verified", "rejected")

    id = db.Column(db.Integer, primary_key=True)
    form_id = db.Column(db.Integer, db.ForeignKey("data_forms.id", ondelete="CASCADE"), nullable=False, index=True)
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="SET NULL"), index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    collected_on = db.Column(db.Date, nullable=False)
    collected_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    answers = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(db.String(12), nullable=False, default="submitted", index=True)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at = db.Column(db.DateTime(timezone=True))
    review_note = db.Column(db.String(500))

    form = db.relationship("DataForm")
    beneficiary = db.relationship("Beneficiary")
    location = db.relationship("Location")
    collected_by = db.relationship("User", foreign_keys=[collected_by_id])
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_id])


# --- Feedback & complaints ----------------------------------------------------------------

class Feedback(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "feedback"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_feedback_org_code"),)

    CHANNELS = {"in_person": "In person", "phone": "Phone call", "hotline": "Hotline", "sms": "SMS / WhatsApp",
                "suggestion_box": "Suggestion box", "community_meeting": "Community meeting", "email": "Email or letter",
                "online": "Online form", "other": "Other"}
    CATEGORIES = {"question": "Question or request for information", "suggestion": "Suggestion",
                  "appreciation": "Appreciation", "complaint": "Complaint about a service",
                  "safeguarding": "Safeguarding concern (abuse, exploitation, harassment)",
                  "fraud": "Fraud or corruption", "misconduct": "Staff or partner misconduct"}
    SENSITIVE = ("safeguarding", "fraud", "misconduct")
    STATUSES = ("new", "acknowledged", "in_progress", "responded", "closed")
    OPEN = ("new", "acknowledged", "in_progress")
    # days to respond, by priority
    RESPONSE_DAYS = {"urgent": 1, "high": 3, "normal": 7, "low": 14}
    SATISFACTION = {"satisfied": "Satisfied", "partly": "Partly satisfied", "not_satisfied": "Not satisfied",
                    "unknown": "Could not be reached"}

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    channel = db.Column(db.String(20), nullable=False, default="in_person")
    category = db.Column(db.String(20), nullable=False, default="question", index=True)
    sensitive = db.Column(db.Boolean, nullable=False, default=False, index=True)
    priority = db.Column(db.String(10), nullable=False, default="normal")
    received_on = db.Column(db.Date, nullable=False)
    received_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    source = db.Column(db.String(10), nullable=False, default="staff")   # staff / public
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="SET NULL"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    beneficiary_id = db.Column(db.Integer, db.ForeignKey("beneficiaries.id", ondelete="SET NULL"), index=True)
    anonymous = db.Column(db.Boolean, nullable=False, default=False)
    submitter_name = db.Column(db.String(200))
    contact_enc = db.Column(db.Text)
    wants_response = db.Column(db.Boolean, nullable=False, default=True)
    summary = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(14), nullable=False, default="new", index=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    due_date = db.Column(db.Date, index=True)
    response = db.Column(db.Text)
    responded_on = db.Column(db.Date)
    closed_on = db.Column(db.Date)
    satisfaction = db.Column(db.String(14))
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    received_by = db.relationship("User", foreign_keys=[received_by_id])
    assigned_to = db.relationship("User", foreign_keys=[assigned_to_id])
    programme = db.relationship("Programme")
    project = db.relationship("Project")
    location = db.relationship("Location")
    beneficiary = db.relationship("Beneficiary")
    actions = db.relationship("FeedbackAction", back_populates="feedback", cascade="all, delete-orphan",
                              order_by="FeedbackAction.created_at")

    @property
    def owner(self):
        return self.project or self.programme


class FeedbackAction(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "feedback_actions"

    id = db.Column(db.Integer, primary_key=True)
    feedback_id = db.Column(db.Integer, db.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(30), nullable=False)
    note = db.Column(db.Text)

    feedback = db.relationship("Feedback", back_populates="actions")
    actor = db.relationship("User")
