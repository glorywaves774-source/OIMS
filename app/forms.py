from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (BooleanField, DecimalField, IntegerField, PasswordField, SelectField,
                     StringField, TextAreaField)
from wtforms.validators import (URL, DataRequired, Email, EqualTo, Length, NumberRange,
                                Optional, ValidationError)

from app.models import Organization, PlatformRole, RolePermission, Subscription

MONTHS = [(i, m) for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], start=1)]

CURRENCIES = [("GHS", "GHS — Ghana cedi"), ("USD", "USD — US dollar"), ("EUR", "EUR — Euro"),
              ("GBP", "GBP — Pound sterling"), ("NGN", "NGN — Naira"), ("KES", "KES — Kenyan shilling"),
              ("XOF", "XOF — CFA franc (BCEAO)"), ("ZAR", "ZAR — Rand"), ("UGX", "UGX — Ugandan shilling"),
              ("TZS", "TZS — Tanzanian shilling")]


def _strip(v):
    return v.strip() if isinstance(v, str) else v


def _lower(v):
    return v.strip().lower() if isinstance(v, str) else v


class ActionForm(FlaskForm):
    """CSRF-only form for button actions."""


class ReasonForm(FlaskForm):
    reason = TextAreaField("Reason", validators=[Optional(), Length(max=500)], filters=[_strip])


# --- Authentication ------------------------------------------------------------

class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=200)])
    remember = BooleanField("Keep me signed in on this device")


class ForgotPasswordForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])


class SetPasswordForm(FlaskForm):
    password = PasswordField("New password", validators=[DataRequired(), Length(max=200)])
    confirm = PasswordField("Confirm new password", validators=[DataRequired(), EqualTo("password", "Passwords do not match.")])


class ChangePasswordForm(SetPasswordForm):
    current_password = PasswordField("Current password", validators=[DataRequired(), Length(max=200)])


class SetupForm(FlaskForm):
    setup_token = PasswordField("Setup token", validators=[DataRequired(), Length(max=200)])
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=200)])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords do not match.")])


class ProfileForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)], filters=[_strip])


# --- Organizations ----------------------------------------------------------------

class OrganizationFieldsMixin:
    name = StringField("Organization name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    org_type = SelectField("Organization type", choices=[(t, t) for t in Organization.TYPES], validators=[DataRequired()])
    registration_number = StringField("Registration number", validators=[Optional(), Length(max=120)], filters=[_strip])
    address = StringField("Physical address", validators=[Optional(), Length(max=300)], filters=[_strip])
    country = StringField("Country", default="Ghana", validators=[DataRequired(), Length(max=80)], filters=[_strip])
    region = StringField("Region", validators=[Optional(), Length(max=120)], filters=[_strip])
    district = StringField("District", validators=[Optional(), Length(max=120)], filters=[_strip])
    phone = StringField("Telephone", validators=[Optional(), Length(max=50)], filters=[_strip])
    email = StringField("Official email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])
    website = StringField("Website", validators=[Optional(), URL(require_tld=True), Length(max=255)], filters=[_strip])
    description = TextAreaField("Description", validators=[Optional(), Length(max=4000)], filters=[_strip])
    contact_name = StringField("Primary contact person", validators=[Optional(), Length(max=200)], filters=[_strip])
    contact_phone = StringField("Contact phone", validators=[Optional(), Length(max=50)], filters=[_strip])
    contact_email = StringField("Contact email", validators=[Optional(), Email(), Length(max=255)], filters=[_lower])
    logo = FileField("Logo (PNG, JPEG or WebP, max 512 KB)")


class OrganizationRegistrationForm(OrganizationFieldsMixin, FlaskForm):
    plan_id = SelectField("Subscription plan", coerce=int, validators=[Optional()])
    admin_name = StringField("Your full name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    admin_email = StringField("Your email (sign-in)", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])
    password = PasswordField("Password", validators=[DataRequired(), Length(max=200)])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords do not match.")])
    accept = BooleanField("I confirm I am authorized to register this organization", validators=[DataRequired()])


class PlatformCreateOrganizationForm(OrganizationFieldsMixin, FlaskForm):
    plan_id = SelectField("Subscription plan", coerce=int, validators=[Optional()])
    admin_name = StringField("Organization administrator name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    admin_email = StringField("Organization administrator email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])


class OrganizationSettingsForm(OrganizationFieldsMixin, FlaskForm):
    currency = SelectField("Currency", choices=CURRENCIES)
    fiscal_year_start_month = SelectField("Fiscal year starts in", coerce=int, choices=MONTHS)
    timezone = StringField("Time zone", validators=[DataRequired(), Length(max=64)], filters=[_strip])
    require_support_approval = BooleanField("HOLIDO support needs our approval before accessing this workspace")
    remove_logo = BooleanField("Remove current logo")


# --- Platform ----------------------------------------------------------------------

class PlanForm(FlaskForm):
    code = StringField("Code", validators=[DataRequired(), Length(max=40)], filters=[_lower])
    name = StringField("Name", validators=[DataRequired(), Length(max=120)], filters=[_strip])
    description = TextAreaField("Description", validators=[Optional(), Length(max=500)], filters=[_strip])
    currency = SelectField("Currency", choices=CURRENCIES)
    monthly_price = DecimalField("Monthly price", places=2, validators=[DataRequired(message="Enter 0 for free"), NumberRange(min=0)], default=0)
    annual_price = DecimalField("Annual price", places=2, validators=[DataRequired(message="Enter 0 for free"), NumberRange(min=0)], default=0)
    trial_days = IntegerField("Trial days", default=0, validators=[NumberRange(min=0, max=365)])
    max_users = IntegerField("User limit (blank = unlimited)", validators=[Optional(), NumberRange(min=1)])
    max_storage_mb = IntegerField("Storage limit in MB (blank = unlimited)", validators=[Optional(), NumberRange(min=1)])
    is_public = BooleanField("Offered on the public registration form", default=True)
    is_active = BooleanField("Active", default=True)

    def validate_code(self, field):
        import re
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", field.data or ""):
            raise ValidationError("Use lowercase letters, numbers, - and _ only.")


class AssignPlanForm(FlaskForm):
    plan_id = SelectField("Plan", coerce=int, validators=[DataRequired()])
    status = SelectField("Status", choices=[(s, s.replace("_", " ").title()) for s in Subscription.STATUSES])
    billing_cycle = SelectField("Billing cycle", choices=[("monthly", "Monthly"), ("annual", "Annual")])
    current_period_end = StringField("Current period ends (YYYY-MM-DD)", validators=[Optional(), Length(max=10)])


class PlatformStaffForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])
    platform_role = SelectField("Platform role", choices=list(PlatformRole.LABELS.items()))


class SupportRequestForm(FlaskForm):
    reason = TextAreaField("Reason for access (shared with the organization)",
                           validators=[DataRequired(), Length(min=10, max=1000)], filters=[_strip])
    duration_minutes = SelectField("Duration", coerce=int,
                                   choices=[(30, "30 minutes"), (60, "1 hour"), (120, "2 hours")])


# --- Workspace ----------------------------------------------------------------------

class InviteUserForm(FlaskForm):
    full_name = StringField("Full name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)], filters=[_lower])
    role_id = SelectField("Role", coerce=int, validators=[DataRequired()])
    job_title = StringField("Job title", validators=[Optional(), Length(max=150)], filters=[_strip])


class MembershipForm(FlaskForm):
    role_id = SelectField("Role", coerce=int, validators=[DataRequired()])
    job_title = StringField("Job title", validators=[Optional(), Length(max=150)], filters=[_strip])


class RoleForm(FlaskForm):
    name = StringField("Role name", validators=[DataRequired(), Length(max=100)], filters=[_strip])
    description = StringField("Description", validators=[Optional(), Length(max=300)], filters=[_strip])


SCOPE_CHOICES = list(RolePermission.SCOPES.items())
