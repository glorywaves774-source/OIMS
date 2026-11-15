"""Forms for suppliers, purchase requests, quotations, orders, receipts, payments and assets."""
from flask_wtf import FlaskForm
from wtforms import (BooleanField, DateField, DecimalField, IntegerField, SelectField, StringField,
                     TextAreaField)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional

from app.forms_office import _DateOrder, _strip, opt_int
from app.models import Asset, Supplier


class SupplierForm(FlaskForm):
    name = StringField("Supplier name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    category = SelectField("Category", choices=[(c, c) for c in Supplier.CATEGORIES])
    contact_person = StringField("Contact person", validators=[Optional(), Length(max=200)], filters=[_strip])
    phone = StringField("Phone", validators=[Optional(), Length(max=50)], filters=[_strip])
    email = StringField("Email", validators=[Optional(), Email(), Length(max=255)], filters=[_strip])
    address = StringField("Address", validators=[Optional(), Length(max=300)], filters=[_strip])
    tax_id = StringField("Tax ID (TIN)", validators=[Optional(), Length(max=60)], filters=[_strip])
    bank_name = StringField("Bank", validators=[Optional(), Length(max=120)], filters=[_strip])
    bank_account = StringField("Account number", validators=[Optional(), Length(max=60)], filters=[_strip])
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=4000)], filters=[_strip])


class SupplierStatusForm(FlaskForm):
    status = SelectField("Status", choices=[(s, s.capitalize()) for s in Supplier.STATUSES])
    status_reason = StringField("Reason", validators=[Optional(), Length(max=300)], filters=[_strip])
    rating = SelectField("Performance rating", coerce=opt_int, validators=[Optional()],
                         choices=[(0, "— Not rated —")] + [(i, f"{i} of 5") for i in range(1, 6)])


class RequestForm(FlaskForm):
    title = StringField("What is being bought", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    budget_line_id = SelectField("Budget line", coerce=opt_int, validators=[DataRequired(message="Choose a budget line.")])
    activity_id = SelectField("Activity", coerce=opt_int, validators=[Optional()])
    needed_by = DateField("Needed by", validators=[Optional()])
    delivery_location = StringField("Deliver to", validators=[Optional(), Length(max=200)], filters=[_strip])
    justification = TextAreaField("Why it is needed", validators=[DataRequired(), Length(max=4000)], filters=[_strip])


class ItemForm(FlaskForm):
    description = StringField("Item", validators=[DataRequired(), Length(max=300)], filters=[_strip])
    quantity = DecimalField("Quantity", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    unit = StringField("Unit", validators=[DataRequired(), Length(max=30)], filters=[_strip], default="each")
    unit_cost = DecimalField("Estimated unit cost", places=2, validators=[DataRequired(), NumberRange(min=0)])
    is_asset = BooleanField("This is an asset to tag and track (equipment, furniture, vehicles…)")
    asset_category = SelectField("Asset category", choices=[("", "—")] + [(c, c) for c in Asset.CATEGORIES],
                                 default="")


class QuotationForm(FlaskForm):
    supplier_id = SelectField("Supplier", coerce=opt_int, validators=[DataRequired(message="Choose a supplier.")])
    reference = StringField("Quotation reference", validators=[Optional(), Length(max=120)], filters=[_strip])
    received_on = DateField("Received on", validators=[DataRequired()])
    total_amount = DecimalField("Total amount", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    delivery_days = IntegerField("Delivery time (days)", validators=[Optional(), NumberRange(min=0, max=3650)])
    valid_until = DateField("Valid until", validators=[Optional()])
    notes = StringField("Notes", validators=[Optional(), Length(max=500)], filters=[_strip])


class SelectionForm(FlaskForm):
    quotation_id = SelectField("Chosen quotation", coerce=opt_int, validators=[DataRequired(message="Choose one.")])
    selection_reason = TextAreaField("Reason for the choice", validators=[Optional(), Length(max=4000)],
                                     filters=[_strip])
    evaluation_report = TextAreaField("Evaluation report (tenders)", validators=[Optional(), Length(max=20000)],
                                      filters=[_strip])


class OrderForm(FlaskForm):
    order_date = DateField("Order date", validators=[DataRequired()])
    delivery_date = DateField("Delivery expected", validators=[Optional(), _DateOrder("order_date",
                                                                                       "Must be after the order date.")])
    terms = TextAreaField("Terms (delivery, warranty, payment)", validators=[Optional(), Length(max=4000)],
                          filters=[_strip])


class CancelForm(FlaskForm):
    reason = StringField("Reason", validators=[DataRequired(), Length(max=300)], filters=[_strip])


class ReceiptForm(FlaskForm):
    received_on = DateField("Received on", validators=[DataRequired()])
    delivery_note = StringField("Supplier delivery note number", validators=[Optional(), Length(max=120)],
                                filters=[_strip])
    notes = StringField("Notes", validators=[Optional(), Length(max=500)], filters=[_strip])


class PaymentForm(FlaskForm):
    amount = DecimalField("Amount", places=2, validators=[DataRequired(), NumberRange(min=0.01)])
    paid_on = DateField("Payment date", validators=[DataRequired()])
    reference = StringField("Invoice / cheque / transfer reference", validators=[DataRequired(), Length(max=120)],
                            filters=[_strip])


class ThresholdForm(FlaskForm):
    proc_quotes_threshold = DecimalField("Three quotations from", places=2, validators=[DataRequired(),
                                                                                      NumberRange(min=0)])
    proc_tender_threshold = DecimalField("Competitive tender from", places=2, validators=[DataRequired(),
                                                                                        NumberRange(min=0)])

    def validate_proc_tender_threshold(self, field):
        from wtforms.validators import ValidationError
        if self.proc_quotes_threshold.data is not None and field.data <= self.proc_quotes_threshold.data:
            raise ValidationError("Must be higher than the three-quotation amount.")


# --- assets --------------------------------------------------------------------------------

class AssetForm(FlaskForm):
    name = StringField("Asset", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    category = SelectField("Category", choices=[(c, c) for c in Asset.CATEGORIES])
    make_model = StringField("Make and model", validators=[Optional(), Length(max=200)], filters=[_strip])
    serial_number = StringField("Serial / chassis number", validators=[Optional(), Length(max=120)], filters=[_strip])
    description = TextAreaField("Description", validators=[Optional(), Length(max=4000)], filters=[_strip])
    purchase_date = DateField("Purchase date", validators=[Optional()])
    cost = DecimalField("Cost", places=2, validators=[Optional(), NumberRange(min=0)])
    currency = SelectField("Currency")
    useful_life_years = IntegerField("Useful life (years)", validators=[Optional(), NumberRange(min=1, max=50)])
    residual_value = DecimalField("Value at end of life", places=2, validators=[Optional(), NumberRange(min=0)])
    owner = SelectField("Funded by", validators=[Optional()], default="")
    donor_id = SelectField("Donor", coerce=opt_int, validators=[Optional()])
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])
    condition = SelectField("Condition", choices=[(c, c.capitalize()) for c in Asset.CONDITIONS], default="good")
    warranty_until = DateField("Warranty until", validators=[Optional()])
    insured = BooleanField("Insured")
    notes = TextAreaField("Notes", validators=[Optional(), Length(max=4000)], filters=[_strip])


class AssignForm(FlaskForm):
    to_user_id = SelectField("Give to", coerce=opt_int, validators=[DataRequired(message="Choose a person.")])
    happened_on = DateField("Date", validators=[DataRequired()])
    note = StringField("Note", validators=[Optional(), Length(max=500)], filters=[_strip])


class AssetEventForm(FlaskForm):
    happened_on = DateField("Date", validators=[DataRequired()])
    note = TextAreaField("What was done / found", validators=[Optional(), Length(max=4000)], filters=[_strip])
    cost = DecimalField("Cost", places=2, validators=[Optional(), NumberRange(min=0)])
    next_due = DateField("Next service due", validators=[Optional()])
    condition = SelectField("Condition now", choices=[("", "— Unchanged —")] + [(c, c.capitalize()) for c in
                                                                               Asset.CONDITIONS], default="")


class TransferForm(FlaskForm):
    owner = SelectField("Now charged to", validators=[Optional()], default="")
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    department_id = SelectField("Department", coerce=opt_int, validators=[Optional()])
    happened_on = DateField("Date", validators=[DataRequired()])
    note = StringField("Reason", validators=[DataRequired(), Length(max=500)], filters=[_strip])


class DisposalForm(FlaskForm):
    disposal_method = SelectField("How", choices=list(Asset.DISPOSAL_METHODS.items()))
    disposal_value = DecimalField("Money received (if sold)", places=2, validators=[Optional(), NumberRange(min=0)])
    disposal_reason = StringField("Reason", validators=[DataRequired(), Length(max=500)], filters=[_strip])
