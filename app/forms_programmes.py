"""Forms for programmes, results, activities, finance, monitoring and reports."""
from flask_wtf import FlaskForm
from wtforms import (DateField, DecimalField, IntegerField, SelectField, SelectMultipleField,
                     StringField, TextAreaField)
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional

from app.forms import CURRENCIES
from app.forms_office import _DateOrder, _strip, opt_int
from app.models import (Activity, Donor, Evaluation, Expenditure, Indicator, LearningItem, Programme,
                        ProgrammeReport, ResultNode, Workplan)

LONG = 20000


def _txt(label, maxlen=LONG):
    return TextAreaField(label, validators=[Optional(), Length(max=maxlen)], filters=[_strip])


def _money(label, required=False):
    v = [DataRequired(message="Enter an amount."), NumberRange(min=0)] if required else [Optional(), NumberRange(min=0)]
    return DecimalField(label, places=2, validators=v)


class ProgrammeForm(FlaskForm):
    code = StringField("Programme ID", validators=[Optional(), Length(max=40)], filters=[_strip],
                       description="Leave blank to number it automatically (PRG/2026/001).")
    title = StringField("Programme title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    sector = StringField("Sector", validators=[Optional(), Length(max=120)], filters=[_strip])
    description = _txt("Description")
    background = _txt("Background")
    rationale = _txt("Rationale / justification")
    goal = _txt("Goal")
    target_population = _txt("Target population")
    geographic_coverage = _txt("Geographical coverage")
    start_date = DateField("Start date", validators=[Optional()])
    end_date = DateField("End date", validators=[Optional(), _DateOrder("start_date", "Must be after the start date.")])
    manager_id = SelectField("Programme manager", coerce=opt_int, validators=[Optional()])
    department_id = SelectField("Lead department", coerce=opt_int, validators=[Optional()])
    currency = SelectField("Currency", choices=CURRENCIES)
    approved_budget = _money("Approved budget")


class PlanningForm(FlaskForm):
    strategy = _txt("Programme strategy")
    implementation_plan = _txt("Implementation plan")
    theory_of_change = _txt("Theory of change")
    assumptions = _txt("Key assumptions")
    risks_summary = _txt("Main risks")


class StatusForm(FlaskForm):
    status = SelectField("Status", choices=[(s, s.replace("_", " ").capitalize()) for s in Programme.STATUSES])
    note = StringField("Note", validators=[Optional(), Length(max=500)], filters=[_strip])


class TeamForm(FlaskForm):
    user_id = SelectField("Person", coerce=opt_int, validators=[DataRequired(message="Choose a person.")])
    role_label = StringField("Role on the programme", validators=[Optional(), Length(max=100)], filters=[_strip])


class ResultForm(FlaskForm):
    level = SelectField("Level", choices=list(ResultNode.LEVELS.items()))
    parent_id = SelectField("Contributes to", coerce=opt_int, validators=[Optional()])
    code = StringField("Code", validators=[Optional(), Length(max=20)], filters=[_strip])
    statement = TextAreaField("Result statement", validators=[DataRequired(), Length(max=4000)], filters=[_strip])
    assumptions = _txt("Assumptions", maxlen=4000)


class IndicatorForm(FlaskForm):
    code = StringField("Code", validators=[Optional(), Length(max=20)], filters=[_strip])
    name = StringField("Indicator", validators=[DataRequired(), Length(max=400)], filters=[_strip])
    result_id = SelectField("Measures result", coerce=opt_int, validators=[Optional()])
    definition = _txt("Definition / how it is calculated", maxlen=4000)
    unit = SelectField("Unit", choices=[("number", "Number"), ("percent", "Percent"), ("currency", "Amount of money"),
                                        ("score", "Score / index")])
    aggregation = SelectField("How results add up", choices=list(Indicator.AGGREGATIONS.items()))
    direction = SelectField("Good direction", choices=[("increase", "Higher is better"), ("decrease", "Lower is better")])
    baseline_value = DecimalField("Baseline", places=4, validators=[Optional()])
    baseline_date = DateField("Baseline date", validators=[Optional()])
    target_value = DecimalField("Overall target", places=4, validators=[Optional()])
    frequency = SelectField("Reporting frequency", choices=[(f, f.replace("_", " ").capitalize()) for f in Indicator.FREQUENCIES])
    means_of_verification = _txt("Means of verification", maxlen=4000)
    data_source = StringField("Data source / collection tool", validators=[Optional(), Length(max=300)], filters=[_strip])
    responsible_id = SelectField("Responsible", coerce=opt_int, validators=[Optional()])
    disaggregations = SelectMultipleField("Break results down by", choices=[
        ("sex", "Sex"), ("age", "Age group"), ("disability", "Disability")], validators=[Optional()])


class TargetForm(FlaskForm):
    period_label = StringField("Period", validators=[DataRequired(), Length(max=40)], filters=[_strip])
    period_start = DateField("From", validators=[DataRequired()])
    period_end = DateField("To", validators=[DataRequired(), _DateOrder("period_start", "Must be after the start.")])
    target_value = DecimalField("Target", places=4, validators=[DataRequired()])


class ResultEntryForm(FlaskForm):
    period_start = DateField("Period from", validators=[DataRequired()])
    period_end = DateField("Period to", validators=[DataRequired(), _DateOrder("period_start", "Must be after the start.")])
    value = DecimalField("Result", places=4, validators=[DataRequired(message="Enter the result.")])
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    source = StringField("Source / evidence", validators=[Optional(), Length(max=300)], filters=[_strip])
    notes = _txt("Notes", maxlen=4000)


class ReviewNoteForm(FlaskForm):
    note = StringField("Note", validators=[Optional(), Length(max=500)], filters=[_strip])


class WorkplanForm(FlaskForm):
    title = StringField("Workplan", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    period_type = SelectField("Period", choices=list(Workplan.PERIODS.items()))
    start_date = DateField("From", validators=[DataRequired()])
    end_date = DateField("To", validators=[DataRequired(), _DateOrder("start_date", "Must be after the start.")])


class ActivityForm(FlaskForm):
    code = StringField("Code", validators=[Optional(), Length(max=20)], filters=[_strip])
    title = StringField("Activity", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    description = _txt("Description", maxlen=8000)
    category = StringField("Category", validators=[Optional(), Length(max=100)], filters=[_strip])
    workplan_id = SelectField("Workplan", coerce=opt_int, validators=[Optional()])
    result_id = SelectField("Contributes to output", coerce=opt_int, validators=[Optional()])
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    planned_start = DateField("Planned start", validators=[Optional()])
    planned_end = DateField("Planned end", validators=[Optional(), _DateOrder("planned_start", "Must be after the start.")])
    responsible_id = SelectField("Responsible", coerce=opt_int, validators=[Optional()])
    budget_line_id = SelectField("Budget line", coerce=opt_int, validators=[Optional()])
    planned_budget = _money("Activity budget")
    target_participants = IntegerField("Target participants", validators=[Optional(), NumberRange(min=0)])


class ProgressForm(FlaskForm):
    status = SelectField("Status", choices=[(s, s.replace("_", " ").capitalize()) for s in Activity.STATUSES])
    progress = IntegerField("Progress %", validators=[Optional(), NumberRange(min=0, max=100)])
    actual_start = DateField("Actual start", validators=[Optional()])
    actual_end = DateField("Actual end", validators=[Optional(), _DateOrder("actual_start", "Must be after the start.")])


class ActivityReportForm(FlaskForm):
    report_date = DateField("Date carried out", validators=[DataRequired()])
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    participants_female = IntegerField("Female participants", default=0, validators=[Optional(), NumberRange(min=0)])
    participants_male = IntegerField("Male participants", default=0, validators=[Optional(), NumberRange(min=0)])
    participants_youth = IntegerField("Of whom young people (15–35)", validators=[Optional(), NumberRange(min=0)])
    participants_disability = IntegerField("Of whom people with a disability", validators=[Optional(), NumberRange(min=0)])
    summary = TextAreaField("What was done and achieved", validators=[DataRequired(), Length(max=LONG)], filters=[_strip])
    challenges = _txt("Challenges")
    recommendations = _txt("Recommendations")


class MilestoneForm(FlaskForm):
    title = StringField("Milestone", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    due_date = DateField("Due", validators=[DataRequired()])
    notes = StringField("Notes", validators=[Optional(), Length(max=1000)], filters=[_strip])


class BudgetLineForm(FlaskForm):
    category_id = SelectField("Category", coerce=int, validators=[DataRequired()])
    code = StringField("Code", validators=[Optional(), Length(max=30)], filters=[_strip])
    description = StringField("Description", validators=[DataRequired(), Length(max=300)], filters=[_strip])
    amount = _money("Amount", required=True)


class RevisionForm(FlaskForm):
    reason = TextAreaField("Reason for the revision", validators=[DataRequired(), Length(min=10, max=4000)], filters=[_strip])


class FundingForm(FlaskForm):
    donor_id = SelectField("Donor / funding partner", coerce=int, validators=[DataRequired()])
    reference = StringField("Agreement reference", validators=[Optional(), Length(max=120)], filters=[_strip])
    committed_amount = _money("Amount committed", required=True)
    start_date = DateField("From", validators=[Optional()])
    end_date = DateField("To", validators=[Optional(), _DateOrder("start_date", "Must be after the start.")])
    reporting_requirements = _txt("Reporting requirements", maxlen=4000)


class ReceiptForm(FlaskForm):
    agreement_id = SelectField("Agreement", coerce=int, validators=[DataRequired()])
    received_on = DateField("Date received", validators=[DataRequired()])
    amount = _money("Amount received", required=True)
    reference = StringField("Reference", validators=[Optional(), Length(max=120)], filters=[_strip])


class ExpenditureForm(FlaskForm):
    kind = SelectField("Type", choices=list(Expenditure.KINDS.items()))
    budget_line_id = SelectField("Budget line", coerce=int, validators=[DataRequired()])
    activity_id = SelectField("Activity", coerce=opt_int, validators=[Optional()])
    spent_on = DateField("Date", validators=[DataRequired()])
    description = StringField("Description", validators=[DataRequired(), Length(max=300)], filters=[_strip])
    payee = StringField("Paid to", validators=[Optional(), Length(max=200)], filters=[_strip])
    reference = StringField("Voucher / reference", validators=[Optional(), Length(max=120)], filters=[_strip])
    amount = DecimalField("Amount", places=2, validators=[DataRequired(), NumberRange(min=0.01)])


class VisitForm(FlaskForm):
    visit_date = DateField("Date", validators=[DataRequired()])
    location_id = SelectField("Location", coerce=opt_int, validators=[Optional()])
    purpose = StringField("Purpose", validators=[DataRequired(), Length(max=300)], filters=[_strip])
    findings = _txt("Findings")
    recommendations = _txt("Recommendations")
    follow_up = _txt("Follow-up actions")


class EvaluationForm(FlaskForm):
    eval_type = SelectField("Type", choices=[(t, t) for t in Evaluation.TYPES])
    title = StringField("Title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    evaluator = StringField("Evaluator", validators=[Optional(), Length(max=200)], filters=[_strip])
    start_date = DateField("From", validators=[Optional()])
    end_date = DateField("To", validators=[Optional(), _DateOrder("start_date", "Must be after the start.")])
    status = SelectField("Status", choices=[(s, s.capitalize()) for s in Evaluation.STATUSES])
    findings = _txt("Key findings")
    recommendations = _txt("Recommendations")


class LearningForm(FlaskForm):
    kind = SelectField("Type", choices=list(LearningItem.KINDS.items()))
    title = StringField("Title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    description = _txt("Details", maxlen=8000)
    evaluation_id = SelectField("From evaluation", coerce=opt_int, validators=[Optional()])
    responsible_id = SelectField("Responsible", coerce=opt_int, validators=[Optional()])
    due_date = DateField("Due", validators=[Optional()])


class ResponseForm(FlaskForm):
    response_status = SelectField("Response", choices=[(s, s.replace("_", " ").capitalize()) for s in LearningItem.RESPONSE_STATUSES])
    management_response = _txt("Management response", maxlen=8000)


class ReportForm(FlaskForm):
    report_type = SelectField("Type", choices=list(ProgrammeReport.TYPES.items()))
    title = StringField("Title", validators=[DataRequired(), Length(max=250)], filters=[_strip])
    period_start = DateField("Period from", validators=[DataRequired()])
    period_end = DateField("Period to", validators=[DataRequired(), _DateOrder("period_start", "Must be after the start.")])
    due_date = DateField("Due date", validators=[Optional()])
    donor_id = SelectField("Donor (for donor reports)", coerce=opt_int, validators=[Optional()])
    summary = _txt("Executive summary")
    achievements = _txt("Key achievements")
    challenges = _txt("Challenges and how they were addressed")
    lessons = _txt("Lessons learned")
    next_steps = _txt("Plans for the next period")


class DonorForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    donor_type = SelectField("Type", choices=[("", "—")] + [(t, t) for t in Donor.TYPES], validators=[Optional()])
    contact_name = StringField("Contact person", validators=[Optional(), Length(max=200)], filters=[_strip])
    contact_email = StringField("Contact email", validators=[Optional(), Email(), Length(max=255)], filters=[_strip])
    notes = _txt("Notes", maxlen=4000)


class LocationForm(FlaskForm):
    name = StringField("Community / site", validators=[DataRequired(), Length(max=200)], filters=[_strip])
    district = StringField("District", validators=[Optional(), Length(max=120)], filters=[_strip])
    region = StringField("Region", validators=[Optional(), Length(max=120)], filters=[_strip])


class CategoryNameForm(FlaskForm):
    name = StringField("Budget category", validators=[DataRequired(), Length(max=100)], filters=[_strip])

