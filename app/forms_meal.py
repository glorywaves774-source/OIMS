"""Forms for beneficiaries, consent, enrolment, services, data collection and feedback."""
from flask_wtf import FlaskForm
from wtforms import (BooleanField, DateField, DecimalField, IntegerField, SelectField, SelectMultipleField,
                     StringField, TextAreaField)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.forms_office import _strip, opt_int
from app.models import Beneficiary, ConsentRecord, DataForm, Feedback, FormField
from app.models.meal import SEXES


def _choices(d):
    return list(d.items())


class BeneficiaryForm(FlaskForm):
    first_name = StringField("First name", validators=[DataRequired(), Length(max=120)], filters=[_strip])
    other_names = StringField("Other names", validators=[Optional(), Length(max=120)], filters=[_strip])
    last_name = StringField("Surname", validators=[DataRequired(), Length(max=120)], filters=[_strip])
    sex = SelectField("Sex", choices=[("", "— Choose —")] + _choices(SEXES), default="",
                      validators=[DataRequired(message="Choose an option (or “Not stated”).")])
    date_of_birth = DateField("Date of birth", validators=[Optional()])
    age_estimate = IntegerField("Or approximate age (years)", validators=[Optional(), NumberRange(min=0, max=120)])
    disability = SelectField("Living with a disability?", choices=[("", "Not asked"), ("no", "No"), ("yes", "Yes")],
                             default="")
    disability_type = StringField("Type of disability", validators=[Optional(), Length(max=200)], filters=[_strip])
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    community = StringField("Community / village", validators=[Optional(), Length(max=200)], filters=[_strip])
    household_id = SelectField("Household", coerce=opt_int, validators=[Optional()])
    relationship_to_head = SelectField("Relationship to household head",
                                       choices=[("", "—")] + [(r, r) for r in Beneficiary.RELATIONSHIPS], default="")
    phone = StringField("Phone", validators=[Optional(), Length(max=40)], filters=[_strip])
    id_type = SelectField("ID type", choices=[("", "—")] + [(t, t) for t in Beneficiary.ID_TYPES], default="")
    id_number = StringField("ID number", validators=[Optional(), Length(max=60)], filters=[_strip])
    vulnerabilities = SelectMultipleField("Vulnerability", choices=[(v, v) for v in Beneficiary.VULNERABILITIES],
                                          validators=[Optional()])
    notes = TextAreaField("Confidential notes", validators=[Optional(), Length(max=4000)], filters=[_strip])
    confirm_new = BooleanField("I have checked the possible matches: this is a different person")

    def validate_date_of_birth(self, field):
        from datetime import date
        if field.data and field.data > date.today():
            raise ValidationError("Date of birth cannot be in the future.")


class ConsentForm(FlaskForm):
    given_on = DateField("Date", validators=[DataRequired()])
    given_by = SelectField("Consent given by", choices=_choices(ConsentRecord.GIVERS))
    guardian_name = StringField("Name of parent / guardian / caregiver", validators=[Optional(), Length(max=200)],
                                filters=[_strip])
    purposes = SelectMultipleField("Agreed to", choices=_choices(ConsentRecord.PURPOSES),
                                   validators=[DataRequired(message="Choose at least one purpose.")])
    method = SelectField("How it was recorded", choices=_choices(ConsentRecord.METHODS))


class WithdrawForm(FlaskForm):
    note = StringField("Reason or note", validators=[Optional(), Length(max=500)], filters=[_strip])


class EnrollForm(FlaskForm):
    owner = SelectField("Programme or project", validators=[DataRequired(message="Choose where to enrol.")])
    enrolled_on = DateField("Enrolled on", validators=[DataRequired()])


class EndEnrollmentForm(FlaskForm):
    status = SelectField("Outcome", choices=[("completed", "Completed"), ("exited", "Left / dropped out")])
    ended_on = DateField("Date", validators=[DataRequired()])
    end_reason = StringField("Reason", validators=[Optional(), Length(max=300)], filters=[_strip])


class ServiceForm(FlaskForm):
    owner = SelectField("Programme or project", validators=[DataRequired()])
    activity_id = SelectField("Activity", coerce=opt_int, validators=[Optional()], validate_choice=False)
    service_type = StringField("Service or item", validators=[DataRequired(), Length(max=120)], filters=[_strip])
    delivered_on = DateField("Date", validators=[DataRequired()])
    quantity = DecimalField("Quantity", places=2, validators=[Optional(), NumberRange(min=0)])
    unit = StringField("Unit", validators=[Optional(), Length(max=40)], filters=[_strip])
    notes = StringField("Notes", validators=[Optional(), Length(max=500)], filters=[_strip])


class ExitForm(FlaskForm):
    status = SelectField("New status", choices=[("active", "Active"), ("inactive", "Inactive"), ("exited", "Exited")])
    exit_reason = StringField("Reason", validators=[Optional(), Length(max=300)], filters=[_strip])


class MergeForm(FlaskForm):
    duplicate_code = StringField("Code of the duplicate record", validators=[DataRequired(), Length(max=40)],
                                 filters=[_strip])


class HouseholdForm(FlaskForm):
    name = StringField("Household name", validators=[DataRequired(), Length(max=200)], filters=[_strip],
                       description="Usually the head's family name, e.g. “Abdulai household”.")
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    community = StringField("Community / village", validators=[Optional(), Length(max=200)], filters=[_strip])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=4000)], filters=[_strip])


# --- Data collection ---------------------------------------------------------------------

class DataFormForm(FlaskForm):
    title = StringField("Form title", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    description = TextAreaField("Instructions for data collectors", validators=[Optional(), Length(max=4000)],
                                filters=[_strip])
    owner = SelectField("Programme or project", validators=[Optional()], default="")
    beneficiary_link = SelectField("Beneficiary", choices=_choices(DataForm.LINKS))


class FieldForm(FlaskForm):
    label = StringField("Question", validators=[DataRequired(), Length(max=300)], filters=[_strip])
    help_text = StringField("Hint", validators=[Optional(), Length(max=300)], filters=[_strip])
    field_type = SelectField("Answer type", choices=_choices(FormField.TYPES))
    options = TextAreaField("Choices (one per line)", validators=[Optional(), Length(max=4000)], filters=[_strip])
    required = BooleanField("Answer required")

    def validate_options(self, field):
        if self.field_type.data in ("choice", "multi"):
            opts = [o.strip() for o in (field.data or "").splitlines() if o.strip()]
            if len(opts) < 2:
                raise ValidationError("Give at least two choices, one per line.")
            if len(set(o.lower() for o in opts)) != len(opts):
                raise ValidationError("Each choice must be different.")


# --- Feedback ------------------------------------------------------------------------------

class FeedbackForm(FlaskForm):
    received_on = DateField("Received on", validators=[DataRequired()])
    channel = SelectField("How it came in", choices=_choices(Feedback.CHANNELS))
    category = SelectField("Type", choices=_choices(Feedback.CATEGORIES))
    priority = SelectField("Priority", choices=[(p, p.capitalize()) for p in ("low", "normal", "high", "urgent")],
                           default="normal")
    owner = SelectField("About programme or project", validators=[Optional()], default="")
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    anonymous = BooleanField("The person wants to stay anonymous")
    beneficiary_code = StringField("Beneficiary code (if registered)", validators=[Optional(), Length(max=40)],
                                   filters=[_strip])
    submitter_name = StringField("Name", validators=[Optional(), Length(max=200)], filters=[_strip])
    contact = StringField("Phone or other contact", validators=[Optional(), Length(max=200)], filters=[_strip])
    wants_response = BooleanField("The person wants a reply", default=True)
    summary = StringField("Summary", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    description = TextAreaField("What was said", validators=[DataRequired(), Length(max=8000)], filters=[_strip])


class PublicFeedbackForm(FlaskForm):
    category = SelectField("What is it about?", choices=[
        ("question", "A question"), ("suggestion", "A suggestion"), ("appreciation", "Thanks / appreciation"),
        ("complaint", "A complaint about a service"),
        ("safeguarding", "Abuse, exploitation or harassment (handled confidentially)"),
        ("fraud", "Fraud or corruption (handled confidentially)"),
        ("misconduct", "Staff or partner misconduct (handled confidentially)")])
    community = StringField("Your community or town (optional)", validators=[Optional(), Length(max=200)],
                            filters=[_strip])
    message = TextAreaField("Your message", validators=[DataRequired(), Length(min=10, max=4000)], filters=[_strip])
    anonymous = BooleanField("I want to stay anonymous")
    name = StringField("Your name (optional)", validators=[Optional(), Length(max=200)], filters=[_strip])
    contact = StringField("Phone or email for a reply (optional)", validators=[Optional(), Length(max=200)],
                          filters=[_strip])
    website = StringField("Leave this empty", validators=[Optional(), Length(max=0, message="")])  # bot trap


class AssignForm(FlaskForm):
    assigned_to_id = SelectField("Assign to", coerce=opt_int, validators=[DataRequired(message="Choose a person.")])
    note = StringField("Note", validators=[Optional(), Length(max=500)], filters=[_strip])


class RespondForm(FlaskForm):
    response = TextAreaField("Response given to the person", validators=[DataRequired(), Length(max=8000)],
                             filters=[_strip])
    responded_on = DateField("Date of response", validators=[DataRequired()])


class CloseFeedbackForm(FlaskForm):
    satisfaction = SelectField("Was the person satisfied?", choices=_choices(Feedback.SATISFACTION))
    note = StringField("Closing note", validators=[Optional(), Length(max=500)], filters=[_strip])


class FeedbackNoteForm(FlaskForm):
    note = TextAreaField("Note", validators=[DataRequired(), Length(max=4000)], filters=[_strip])


class PublicSettingsForm(FlaskForm):
    accept_public_feedback = BooleanField("Accept feedback through a public page (no sign-in needed)")
    public_feedback_intro = TextAreaField("Message shown at the top of the page",
                                          validators=[Optional(), Length(max=2000)], filters=[_strip])
