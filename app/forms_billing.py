"""Forms for subscription billing (organization side and HOLIDO side)."""
from flask_wtf import FlaskForm
from wtforms import DateField, DecimalField, IntegerField, SelectField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, InputRequired, Length, NumberRange, Optional

from app.forms_office import _strip, opt_int
from app.models.billing import Payment


class ChangePlanForm(FlaskForm):
    plan_id = SelectField("Plan", coerce=opt_int, validators=[DataRequired(message="Choose a plan.")])
    billing_cycle = SelectField("Pay", choices=[("monthly", "Monthly"), ("annual", "Yearly")])


class ManualPaymentForm(FlaskForm):
    method = SelectField("How it was paid", choices=[(k, v) for k, v in Payment.METHODS.items() if k != "paystack"])
    amount = DecimalField("Amount", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    reference = StringField("Bank / mobile money / cheque reference", validators=[DataRequired(), Length(max=120)],
                            filters=[_strip])
    received_on = DateField("Received on", validators=[DataRequired()])
    note = StringField("Note", validators=[Optional(), Length(max=500)], filters=[_strip])


class VoidForm(FlaskForm):
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)], filters=[_strip])


class BillingSettingsForm(FlaskForm):
    company_name = StringField("Name on invoices", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    company_address = TextAreaField("Address", validators=[Optional(), Length(max=1000)], filters=[_strip])
    company_tax_id = StringField("Tax ID (TIN)", validators=[Optional(), Length(max=60)], filters=[_strip])
    company_email = StringField("Billing email", validators=[Optional(), Email(), Length(max=255)], filters=[_strip])
    bank_details = TextAreaField("Bank and mobile money details for transfers", validators=[Optional(), Length(max=2000)],
                                 filters=[_strip])
    tax_label = StringField("Tax name (leave empty for none)", validators=[Optional(), Length(max=60)], filters=[_strip])
    tax_rate = DecimalField("Tax rate (%)", places=2, validators=[InputRequired(), NumberRange(min=0, max=100)])
    invoice_days_before = IntegerField("Issue invoices this many days before the period starts",
                                       validators=[InputRequired(), NumberRange(min=0, max=60)])
    grace_days = IntegerField("Days of full access after an unpaid period ends",
                              validators=[InputRequired(), NumberRange(min=0, max=90)])
    invoice_footer = TextAreaField("Footer on invoices", validators=[Optional(), Length(max=1000)], filters=[_strip])
