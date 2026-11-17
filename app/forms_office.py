"""Forms for the Phase 2 office modules."""
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (BooleanField, DateField, DateTimeLocalField, IntegerField, SelectField,
                     SelectMultipleField, StringField, TextAreaField)
from wtforms.validators import URL, DataRequired, Email, Length, NumberRange, Optional, ValidationError

from app.models import (AttendanceRecord, Correspondence, Document, StaffProfile, Task)


def _strip(v):
    return v.strip() if isinstance(v, str) else v


def _lower(v):
    return v.strip().lower() if isinstance(v, str) else v


def opt_int(v):
    """Coerce select values where 0 / '' means 'none'."""
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    return v or None


class _DateOrder:
    def __init__(self, start_field, message):
        self.start_field, self.message = start_field, message

    def __call__(self, form, field):
        start = form[self.start_field].data
        if start and field.data and field.data < start:
            raise ValidationError(self.message)


# --- Departments & staff ------------------------------------------------------------

class DepartmentForm(FlaskForm):
    name = StringField("Department name", validators=[DataRequired(), Length(max=150)], filters=[_strip])
    code = StringField("Short code", validators=[Optional(), Length(max=20)], filters=[_strip])
    head_staff_id = SelectField("Head of department", coerce=opt_int, validators=[Optional()])
    description = TextAreaField("Description", validators=[Optional(), Length(max=4000)], filters=[_strip])
    responsibilities = TextAreaField("Responsibilities", validators=[Optional(), Length(max=8000)], filters=[_strip])


class StaffForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    employee_number = StringField("Staff ID / employee number", validators=[DataRequired(), Length(max=40)], filters=[_strip])
    user_id = SelectField("ZENTAVA OIMS sign-in (optional)", coerce=opt_int, validators=[Optional()])
    email = StringField("Work email", validators=[Optional(), Email(), Length(max=255)], filters=[_lower])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)], filters=[_strip])
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])
    position = StringField("Position / designation", validators=[Optional(), Length(max=150)], filters=[_strip])
    employment_type = SelectField("Employment type", choices=[("", "—")] + [(t, t) for t in StaffProfile.TYPES],
                                  validators=[Optional()])
    status = SelectField("Employment status", choices=[(s, s.replace("_", " ").capitalize()) for s in StaffProfile.STATUSES if s != "exited"])
    start_date = DateField("Start date", validators=[Optional()])
    contract_end_date = DateField("Contract end date", validators=[Optional(), _DateOrder("start_date", "Must be after the start date.")])
    work_location = StringField("Work location", validators=[Optional(), Length(max=150)], filters=[_strip])
    emergency_name = StringField("Emergency contact name", validators=[Optional(), Length(max=200)], filters=[_strip])
    emergency_phone = StringField("Emergency contact phone", validators=[Optional(), Length(max=50)], filters=[_strip])
    emergency_relationship = StringField("Relationship", validators=[Optional(), Length(max=80)], filters=[_strip])
    notes = TextAreaField("HR notes", validators=[Optional(), Length(max=4000)], filters=[_strip])


class TrainingForm(FlaskForm):
    title = StringField("Training", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    provider = StringField("Provider", validators=[Optional(), Length(max=200)], filters=[_strip])
    start_date = DateField("From", validators=[Optional()])
    end_date = DateField("To", validators=[Optional(), _DateOrder("start_date", "Must be after the start date.")])
    outcome = StringField("Outcome / certificate", validators=[Optional(), Length(max=300)], filters=[_strip])


class ReviewForm(FlaskForm):
    period = StringField("Review period", validators=[DataRequired(), Length(max=60)], filters=[_strip])
    rating = SelectField("Rating", coerce=opt_int, choices=[(0, "Not rated"), (1, "1 — Unsatisfactory"),
                         (2, "2 — Needs improvement"), (3, "3 — Meets expectations"), (4, "4 — Exceeds expectations"),
                         (5, "5 — Outstanding")], validators=[Optional()])
    summary = TextAreaField("Summary", validators=[Optional(), Length(max=4000)], filters=[_strip])
    goals = TextAreaField("Goals for next period", validators=[Optional(), Length(max=4000)], filters=[_strip])


class TransferForm(FlaskForm):
    to_department_id = SelectField("New department", coerce=opt_int, validators=[Optional()])
    to_position = StringField("New position", validators=[Optional(), Length(max=150)], filters=[_strip])
    effective_date = DateField("Effective date", validators=[DataRequired()])
    reason = StringField("Reason", validators=[Optional(), Length(max=500)], filters=[_strip])


class ExitForm(FlaskForm):
    exit_date = DateField("Exit date", validators=[DataRequired()])
    exit_type = SelectField("Type of exit", choices=[(t, t) for t in StaffProfile.EXIT_TYPES])
    exit_reason = TextAreaField("Notes", validators=[Optional(), Length(max=2000)], filters=[_strip])
    exit_clearance_done = BooleanField("Clearance completed (handover, assets, final pay)")
    remove_access = BooleanField("Also suspend their ZENTAVA OIMS sign-in for this organization", default=True)


class LeaveTypeForm(FlaskForm):
    name = StringField("Leave type", validators=[DataRequired(), Length(max=80)], filters=[_strip])
    days_per_year = IntegerField("Days per year (blank = no fixed entitlement)", validators=[Optional(), NumberRange(min=1, max=366)])


class LeaveRequestForm(FlaskForm):
    leave_type_id = SelectField("Type of leave", coerce=int, validators=[DataRequired()])
    start_date = DateField("First day", validators=[DataRequired()])
    end_date = DateField("Last day", validators=[DataRequired(), _DateOrder("start_date", "The last day must be on or after the first day.")])
    reason = TextAreaField("Reason (optional)", validators=[Optional(), Length(max=1000)], filters=[_strip])


class DecisionForm(FlaskForm):
    note = StringField("Note (optional)", validators=[Optional(), Length(max=500)], filters=[_strip])


ATTENDANCE_CHOICES = [(s, s.replace("_", " ").capitalize()) for s in AttendanceRecord.STATUSES]


# --- Documents ----------------------------------------------------------------------

class DocumentForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    description = TextAreaField("Description", validators=[Optional(), Length(max=4000)], filters=[_strip])
    folder_id = SelectField("Folder", coerce=opt_int, validators=[Optional()])
    category_id = SelectField("Category", coerce=opt_int, validators=[Optional()])
    visibility = SelectField("Who can see it", choices=list(Document.VISIBILITY.items()))
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])
    shared_with = SelectMultipleField("Share with", coerce=int, validators=[Optional()])
    expiry_date = DateField("Expiry / review date", validators=[Optional()])
    submit_for_approval = BooleanField("Submit for approval")


class UploadForm(DocumentForm):
    file = FileField("File")
    related_type = StringField(validators=[Optional(), Length(max=40)])
    related_id = IntegerField(validators=[Optional()])


class VersionForm(FlaskForm):
    file = FileField("New version")
    note = StringField("What changed", validators=[Optional(), Length(max=300)], filters=[_strip])


class FolderForm(FlaskForm):
    name = StringField("Folder name", validators=[DataRequired(), Length(max=150)], filters=[_strip])
    parent_id = SelectField("Inside", coerce=opt_int, validators=[Optional()])


class CategoryForm(FlaskForm):
    name = StringField("Category", validators=[DataRequired(), Length(max=100)], filters=[_strip])
    requires_approval = BooleanField("Documents in this category need approval")


# --- Correspondence -----------------------------------------------------------------

class CorrespondenceForm(FlaskForm):
    kind = SelectField("Type", choices=[(k, v[1]) for k, v in Correspondence.KINDS.items()])
    subject = StringField("Subject", validators=[DataRequired(), Length(max=300)], filters=[_strip])
    party = StringField("From / to", validators=[Optional(), Length(max=250)], filters=[_strip])
    external_reference = StringField("Their reference", validators=[Optional(), Length(max=120)], filters=[_strip])
    letter_date = DateField("Date on the letter", validators=[Optional()])
    received_date = DateField("Date received / sent", validators=[Optional()])
    summary = TextAreaField("Summary", validators=[Optional(), Length(max=8000)], filters=[_strip])
    priority = SelectField("Priority", choices=[(p, p.capitalize()) for p in Correspondence.PRIORITIES])
    confidential = BooleanField("Confidential (visible only to the people handling it and records managers)")
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])
    assigned_to_id = SelectField("Assign to", coerce=opt_int, validators=[Optional()])
    response_due = DateField("Response due", validators=[Optional()])
    file = FileField("Scanned letter / attachment (optional)")


class RouteForm(FlaskForm):
    to_user_id = SelectField("Send to", coerce=opt_int, validators=[DataRequired(message="Choose a person.")])
    note = TextAreaField("Instructions", validators=[Optional(), Length(max=2000)], filters=[_strip])


class NoteForm(FlaskForm):
    note = TextAreaField("Note", validators=[DataRequired(), Length(max=4000)], filters=[_strip])


# --- Meetings -----------------------------------------------------------------------

def _https_only(form, field):
    if field.data and not field.data.lower().startswith("https://"):
        raise ValidationError("Use a secure link that starts with https://")


class MeetingForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    meeting_type = StringField("Type (e.g. Management, Staff, Board)", validators=[Optional(), Length(max=80)], filters=[_strip])
    starts_at = DateTimeLocalField("Starts", format="%Y-%m-%dT%H:%M", validators=[DataRequired()])
    ends_at = DateTimeLocalField("Ends", format="%Y-%m-%dT%H:%M", validators=[Optional(), _DateOrder("starts_at", "Must end after it starts.")])
    location = StringField("Venue", validators=[Optional(), Length(max=250)], filters=[_strip])
    video_call = BooleanField("Video call in ZENTAVA OIMS", default=True)
    online_link = StringField("Or a Google Meet, Zoom or Teams link", validators=[Optional(), URL(), Length(max=500), _https_only],
                              filters=[_strip])
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])
    participants = SelectMultipleField("Participants", coerce=int, validators=[Optional()])
    agenda = TextAreaField("Agenda", validators=[Optional(), Length(max=8000)], filters=[_strip])


class MinutesForm(FlaskForm):
    minutes = TextAreaField("Minutes", validators=[Optional(), Length(max=50000)], filters=[_strip])


class DecisionTextForm(FlaskForm):
    text = TextAreaField("Decision", validators=[DataRequired(), Length(max=2000)], filters=[_strip])


class ActionPointForm(FlaskForm):
    title = StringField("Action point", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    assigned_to_id = SelectField("Responsible", coerce=opt_int, validators=[DataRequired(message="Choose a person.")])
    due_date = DateField("Follow-up deadline", validators=[Optional()])


# --- Tasks --------------------------------------------------------------------------

class TaskForm(FlaskForm):
    title = StringField("Task", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    description = TextAreaField("Details", validators=[Optional(), Length(max=8000)], filters=[_strip])
    assigned_to_id = SelectField("Assign to", coerce=opt_int, validators=[Optional()])
    priority = SelectField("Priority", choices=[(p, p.capitalize()) for p in Task.PRIORITIES], default="normal")
    due_date = DateField("Deadline", validators=[Optional()])
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])


class TaskStatusForm(FlaskForm):
    status = SelectField("Status", choices=[(s, s.replace("_", " ").capitalize()) for s in Task.STATUSES])


class CommentForm(FlaskForm):
    body = TextAreaField("Comment", validators=[DataRequired(), Length(max=4000)], filters=[_strip])


# --- Communication ------------------------------------------------------------------

class AnnouncementForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    body = TextAreaField("Message", validators=[DataRequired(), Length(max=10000)], filters=[_strip])
    department_id = SelectField("Audience", coerce=opt_int, validators=[Optional()])
    pinned = BooleanField("Pin to the top")
    expires_on = DateField("Show until", validators=[Optional()])


class NewMessageForm(FlaskForm):
    recipients = SelectMultipleField("To", coerce=int, validators=[DataRequired(message="Choose at least one person.")])
    subject = StringField("Subject", validators=[Optional(), Length(max=200)], filters=[_strip])
    body = TextAreaField("Message", validators=[DataRequired(), Length(max=10000)], filters=[_strip])


class ReplyForm(FlaskForm):
    body = TextAreaField("Reply", validators=[DataRequired(), Length(max=10000)], filters=[_strip])
