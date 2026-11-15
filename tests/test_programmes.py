"""Phase 3: programmes management."""
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import (Activity, AuditLog, BudgetCategory, BudgetLine, BudgetRevision, Donor,
                        Expenditure, FundingAgreement, Indicator, IndicatorResult, LearningItem, Milestone,
                        MonitoringVisit, Notification, Programme, ProgrammeReport, ProgrammeTeamMember, ResultNode,
                        Workplan)
from tests.conftest import add_member, login, logout, make_department, make_org, make_staff_profile

YEAR = date.today().year


@pytest.fixture
def env(app, db):
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    prog_dept = make_department(o, "Programmes")
    people = {"org": o, "dept": prog_dept}
    for key, role, dept in [("pd", "Programme Director", prog_dept), ("po", "Programme Officer", prog_dept),
                            ("po2", "Programme Officer", None), ("meal", "MEAL Officer", None),
                            ("fin", "Finance Officer", None), ("fin2", "Finance Officer", None),
                            ("ed", "Executive Director", None), ("field", "Field Officer", None),
                            ("staff", "Staff Member", prog_dept), ("head", "Department Head", prog_dept),
                            ("auditor", "Read-only / Auditor", None)]:
        u, _ = add_member(o, f"{key}@hope.org", role_name=role)
        people[key] = u
        make_staff_profile(o, u, department=dept)
    return people


def P(env, path=""):
    return f"/o/{env['org'].slug}/programmes{path}"


def make_programme(client, env, **over):
    data = {"title": "Girls' Education Programme", "sector": "Education", "manager_id": env["pd"].id,
            "department_id": env["dept"].id, "currency": "GHS", "approved_budget": "100000",
            "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR + 2}-12-31"}
    data.update(over)
    login(client, "pd@hope.org")
    r = client.post(P(env, "/new"), data=data)
    assert r.status_code == 302, r.data[:500]
    prog = Programme.query.filter_by(title=data["title"]).one()
    # add team: po and field officer
    for key in ("po", "field"):
        client.post(P(env, f"/{prog.id}/team"), data={"user_id": env[key].id, "role_label": "Team"})
    logout(client)
    return prog


def as_(client, key):
    logout(client)
    login(client, f"{key}@hope.org")


# --- Registration, visibility, status ---------------------------------------------------------

def test_register_and_visibility(client, env, db):
    prog = make_programme(client, env)
    assert prog.code == f"PRG/{YEAR}/001"
    assert prog.duration_months == 36
    assert {t.user_id for t in prog.team} == {env["po"].id, env["field"].id}
    assert Notification.query.filter_by(user_id=env["po"].id, kind="programme").count() == 1

    as_(client, "staff")
    assert client.get(P(env, "/")).status_code == 403
    as_(client, "po2")  # sees all programmes, but edits only own
    assert client.get(P(env, f"/{prog.id}")).status_code == 200
    assert client.get(P(env, f"/{prog.id}/edit")).status_code == 403
    as_(client, "po")   # team member: may edit
    assert client.get(P(env, f"/{prog.id}/edit")).status_code == 200
    assert client.post(P(env, f"/{prog.id}/status"), data={"status": "planned"}).status_code == 403
    as_(client, "head")  # department scope
    assert client.get(P(env, f"/{prog.id}")).status_code == 200


def test_own_scope_only_sees_team_programmes(client, env):
    prog = make_programme(client, env)
    other = make_programme(client, env, title="Water Programme")
    db_team = ProgrammeTeamMember.query.filter_by(programme_id=other.id, user_id=env["field"].id).one()
    from app.extensions import db
    db.session.delete(db_team)
    db.session.commit()
    as_(client, "field")
    listing = client.get(P(env, "/")).data
    assert b"Girls&#39; Education" in listing and b"Water Programme" not in listing
    assert client.get(P(env, f"/{other.id}")).status_code == 404
    assert client.get(P(env, f"/{prog.id}")).status_code == 200


def test_status_flow(client, env, db):
    prog = make_programme(client, env)
    login(client, "pd@hope.org")
    r = client.post(P(env, f"/{prog.id}/status"), data={"status": "active"}, follow_redirects=True)
    assert b"cannot move to active" in r.data
    client.post(P(env, f"/{prog.id}/status"), data={"status": "planned"})
    client.post(P(env, f"/{prog.id}/status"), data={"status": "approved", "note": "Board approved"})
    db.session.expire_all()
    p = db.session.get(Programme, prog.id)
    assert p.status == "approved" and p.approved_by_id == env["pd"].id and p.status_note == "Board approved"


# --- Results framework & indicators ------------------------------------------------------------

def test_results_framework(client, env):
    prog = make_programme(client, env)
    login(client, "meal@hope.org")
    client.post(P(env, f"/{prog.id}/results"), data={"level": "goal", "code": "G", "statement": "Girls complete school"})
    goal = ResultNode.query.filter_by(level="goal").one()
    client.post(P(env, f"/{prog.id}/results"), data={"level": "outcome", "code": "1", "statement": "Higher attendance",
                                                     "parent_id": goal.id})
    out = ResultNode.query.filter_by(level="outcome").one()
    client.post(P(env, f"/{prog.id}/results"), data={"level": "output", "code": "1.1", "statement": "Teachers trained",
                                                     "parent_id": out.id})
    output = ResultNode.query.filter_by(level="output").one()
    r = client.post(P(env, f"/{prog.id}/results"), data={"level": "outcome", "statement": "Bad", "parent_id": output.id})
    assert b"higher-level result" in r.data
    html = client.get(P(env, f"/{prog.id}/results")).data.decode()
    assert html.index("Girls complete school") < html.index("Higher attendance") < html.index("Teachers trained")
    r = client.post(P(env, f"/{prog.id}/results/{goal.id}/delete"), follow_redirects=True)
    assert b"Remove or move the results under it first" in r.data


def _indicator(client, env, prog, **over):
    data = {"code": "1.1a", "name": "Number of teachers trained", "unit": "number", "aggregation": "sum",
            "direction": "increase", "baseline_value": "0", "target_value": "200", "frequency": "quarterly",
            "disaggregations": ["sex"]}
    data.update(over)
    as_(client, "meal")
    assert client.post(P(env, f"/{prog.id}/indicators/new"), data=data).status_code == 302
    logout(client)
    return Indicator.query.filter_by(name=data["name"]).one()


def report_result(client, env, prog, ind, start, end, value, **extra):
    data = {"what": "result", "r-period_start": start, "r-period_end": end, "r-value": str(value)}
    data.update(extra)
    return client.post(P(env, f"/{prog.id}/indicators/{ind.id}"), data=data, follow_redirects=True)


def test_indicator_results_verification_and_no_double_counting(client, env, db):
    prog = make_programme(client, env)
    ind = _indicator(client, env, prog)
    login(client, "field@hope.org")
    r = report_result(client, env, prog, ind, f"{YEAR}-01-01", f"{YEAR}-03-31", 50, bd_sex_0="30", bd_sex_1="15")
    assert b"adds up to 45" in r.data
    r = report_result(client, env, prog, ind, f"{YEAR}-01-01", f"{YEAR}-03-31", 50, bd_sex_0="30", bd_sex_1="20")
    assert b"submitted for verification" in r.data
    res = IndicatorResult.query.one()
    assert res.breakdown == {"sex": {"Female": 30.0, "Male": 20.0}} and res.status == "submitted"
    # same period again would double count
    r = report_result(client, env, prog, ind, f"{YEAR}-02-01", f"{YEAR}-04-30", 10)
    assert b"already covers this period" in r.data
    assert client.post(P(env, f"/{prog.id}/indicators/{ind.id}/results/{res.id}/verify"), data={}).status_code == 403
    as_(client, "meal")
    html = client.get(P(env, f"/{prog.id}/indicators")).data.decode()
    assert "1 to verify" in html
    client.post(P(env, f"/{prog.id}/indicators/{ind.id}/results/{res.id}/verify"), data={"note": "Checked registers"})
    as_(client, "field")
    report_result(client, env, prog, ind, f"{YEAR}-04-01", f"{YEAR}-06-30", 30)
    as_(client, "meal")
    r2 = IndicatorResult.query.filter_by(status="submitted").one()
    client.post(P(env, f"/{prog.id}/indicators/{ind.id}/results/{r2.id}/verify"), data={})
    from app.programme_logic import achievement, indicator_actual
    db.session.expire_all()
    ind = db.session.get(Indicator, ind.id)
    actual = indicator_actual(ind)
    assert actual == Decimal("80") and achievement(ind, actual) == 40.0
    assert Notification.query.filter_by(user_id=env["field"].id, kind="meal").count() == 2


def test_latest_and_decreasing_indicators(client, env, db):
    prog = make_programme(client, env)
    ind = _indicator(client, env, prog, name="Dropout rate", unit="percent", aggregation="latest",
                     direction="decrease", baseline_value="20", target_value="10", disaggregations=[])
    login(client, "meal@hope.org")
    report_result(client, env, prog, ind, f"{YEAR}-01-01", f"{YEAR}-03-31", 18)
    report_result(client, env, prog, ind, f"{YEAR}-04-01", f"{YEAR}-06-30", 15)
    # MEAL officer reported them; a different MEAL-capable person verifies
    as_(client, "pd")
    for r in IndicatorResult.query.all():
        client.post(P(env, f"/{prog.id}/indicators/{ind.id}/results/{r.id}/verify"), data={})
    from app.programme_logic import achievement, indicator_actual
    actual = indicator_actual(db.session.get(Indicator, ind.id))
    assert actual == Decimal("15")
    assert achievement(ind, actual) == 50.0  # halfway from 20 down to 10


# --- Workplans, activities, milestones -----------------------------------------------------------

def test_workplans_activities_and_timeline(client, env, db):
    prog = make_programme(client, env)
    login(client, "po@hope.org")
    client.post(P(env, f"/{prog.id}/workplans"), data={"what": "workplan", "w-title": f"Annual workplan {YEAR}",
                                                       "w-period_type": "annual", "w-start_date": f"{YEAR}-01-01",
                                                       "w-end_date": f"{YEAR}-12-31"})
    wp = Workplan.query.one()
    start = date.today() - timedelta(days=10)
    r = client.post(P(env, f"/{prog.id}/activities/new"), data={
        "code": "1.1.1", "title": "Teacher training workshop", "workplan_id": wp.id, "responsible_id": env["field"].id,
        "planned_start": start.isoformat(), "planned_end": (start + timedelta(days=5)).isoformat(),
        "planned_budget": "5000", "target_participants": "40"})
    assert r.status_code == 302
    act = Activity.query.one()
    assert Notification.query.filter_by(user_id=env["field"].id, kind="programme").count() >= 1
    client.post(P(env, f"/{prog.id}/workplans"), data={"what": "milestone", "m-title": "Baseline done",
                                                       "m-due_date": date.today().isoformat()})
    html = client.get(P(env, f"/{prog.id}/workplans")).data.decode()
    assert "<svg class=\"gantt\"" in html and "Teacher training workshop" in html and 'class="bar late"' in html
    assert client.post(P(env, f"/{prog.id}/workplans/{wp.id}/approve")).status_code == 403  # needs manage
    as_(client, "field")  # responsible person updates progress and reports
    client.post(P(env, f"/{prog.id}/activities/{act.id}/progress"), data={"status": "in_progress", "progress": "60"})
    r = client.post(P(env, f"/{prog.id}/activities/{act.id}/report"), data={
        "report_date": start.isoformat(), "participants_female": "20", "participants_male": "15",
        "participants_youth": "50", "summary": "Training held"}, follow_redirects=True)
    assert b"cannot exceed it" in r.data
    client.post(P(env, f"/{prog.id}/activities/{act.id}/report"), data={
        "report_date": start.isoformat(), "participants_female": "20", "participants_male": "15",
        "participants_youth": "12", "summary": "Training held", "challenges": "Rain delayed start"})
    db.session.expire_all()
    a = db.session.get(Activity, act.id)
    assert a.progress == 60 and a.status == "in_progress" and len(a.reports) == 1 and a.reports[0].participants_total == 35
    assert client.get(P(env, f"/{prog.id}/activities/{act.id}/edit")).status_code == 403  # field officer can't edit plan
    as_(client, "pd")
    client.post(P(env, f"/{prog.id}/workplans/{wp.id}/approve"))
    assert db.session.get(Workplan, wp.id).status == "approved"


# --- Finance -------------------------------------------------------------------------------------------

def _line(client, env, prog, desc, amount, cat="Training and workshops"):
    c = BudgetCategory.query.filter_by(organization_id=env["org"].id, name=cat).one()
    client.post(P(env, f"/{prog.id}/finance/lines"), data={"b-category_id": c.id, "b-description": desc, "b-amount": amount})
    return BudgetLine.query.filter_by(description=desc).one()


def _spend(client, env, prog, line, amount, kind="expenditure", desc="Workshop venue"):
    client.post(P(env, f"/{prog.id}/finance/expenditure"), data={
        "x-kind": kind, "x-budget_line_id": line.id, "x-spent_on": date.today().isoformat(), "x-description": desc,
        "x-amount": str(amount)})
    return Expenditure.query.filter_by(description=desc).order_by(Expenditure.id.desc()).first()


def test_budget_expenditure_and_separation_of_duties(client, env, db):
    prog = make_programme(client, env)
    login(client, "fin@hope.org")
    train = _line(client, env, prog, "Teacher workshops", "10000")
    _line(client, env, prog, "Field travel", "5000", cat="Travel and transport")
    e = _spend(client, env, prog, train, 4000)
    assert e.status == "pending"
    r = client.post(P(env, f"/{prog.id}/finance/expenditure/{e.id}/approve"), data={}, follow_redirects=True)
    assert b"different person must approve" in r.data
    as_(client, "fin2")
    client.post(P(env, f"/{prog.id}/finance/expenditure/{e.id}/approve"), data={})
    as_(client, "fin")
    c = _spend(client, env, prog, train, 3000, kind="commitment", desc="Printing order")
    big = _spend(client, env, prog, train, 9000, desc="Too much")
    as_(client, "fin2")
    client.post(P(env, f"/{prog.id}/finance/expenditure/{c.id}/approve"), data={})
    r = client.post(P(env, f"/{prog.id}/finance/expenditure/{big.id}/approve"), data={}, follow_redirects=True)
    assert b"Not enough left" in r.data
    from app.programme_logic import finance_summary, line_figures
    db.session.expire_all()
    fs = finance_summary(db.session.get(Programme, prog.id))
    assert fs["budget"] == Decimal("15000") and fs["spent"] == Decimal("4000") and fs["committed"] == Decimal("3000")
    assert fs["available"] == Decimal("8000") and fs["pending"] == Decimal("9000")
    assert round(fs["utilization"], 2) == 26.67
    as_(client, "fin")
    client.post(P(env, f"/{prog.id}/finance/expenditure/{c.id}/cancel"), data={})  # release the commitment
    assert line_figures(db.session.get(BudgetLine, train.id))["available"] == Decimal("6000")
    # Programme officers (not on finance) cannot record or approve
    as_(client, "po")
    assert client.post(P(env, f"/{prog.id}/finance/expenditure"), data={}).status_code == 403
    as_(client, "staff")
    assert client.get(P(env, f"/{prog.id}/finance")).status_code in (403, 404)


def test_budget_revisions_after_approval(client, env, db):
    prog = make_programme(client, env)
    login(client, "fin@hope.org")
    line = _line(client, env, prog, "Teacher workshops", "10000")
    e = _spend(client, env, prog, line, 6000)
    as_(client, "ed")
    client.post(P(env, f"/{prog.id}/finance/expenditure/{e.id}/approve"), data={})
    as_(client, "pd")
    client.post(P(env, f"/{prog.id}/status"), data={"status": "planned"})
    client.post(P(env, f"/{prog.id}/status"), data={"status": "approved"})
    as_(client, "fin")
    r = client.post(P(env, f"/{prog.id}/finance/lines/{line.id}"), data={"b-amount": "1"}, follow_redirects=True)
    assert b"Request a budget revision" in r.data
    r = client.post(P(env, f"/{prog.id}/finance/revisions"), data={"reason": "Reduce workshops", f"new_{line.id}": "5000"},
                    follow_redirects=True)
    assert b"cannot go below" in r.data
    client.post(P(env, f"/{prog.id}/finance/revisions"), data={"reason": "More teachers enrolled", f"new_{line.id}": "14000"})
    rev = BudgetRevision.query.one()
    assert rev.status == "pending" and db.session.get(BudgetLine, line.id).amount == Decimal("10000")
    r = client.post(P(env, f"/{prog.id}/finance/revisions/{rev.id}/approve"), data={}, follow_redirects=True)
    assert b"different person must approve" in r.data
    as_(client, "ed")
    client.post(P(env, f"/{prog.id}/finance/revisions/{rev.id}/approve"), data={})
    db.session.expire_all()
    ln = db.session.get(BudgetLine, line.id)
    assert ln.amount == Decimal("14000") and ln.original_amount == Decimal("10000")
    assert AuditLog.query.filter_by(action="budget.revision_approve").count() == 1


def test_funding(client, env, db):
    prog = make_programme(client, env)
    login(client, "fin@hope.org")
    client.post(f"/o/{env['org'].slug}/registers/", data={"what": "donor", "d-name": "Global Education Fund",
                                                          "d-donor_type": "Foundation"})
    donor = Donor.query.one()
    client.post(P(env, f"/{prog.id}/finance/funding"), data={"what": "agreement", "f-donor_id": donor.id,
                                                             "f-reference": "GEF-2026-14", "f-committed_amount": "80000"})
    ag = FundingAgreement.query.one()
    client.post(P(env, f"/{prog.id}/finance/funding"), data={"what": "receipt", "r-agreement_id": ag.id,
                                                             "r-received_on": date.today().isoformat(), "r-amount": "30000"})
    from app.programme_logic import finance_summary
    fs = finance_summary(db.session.get(Programme, prog.id))
    assert fs["funding_committed"] == Decimal("80000") and fs["funding_received"] == Decimal("30000")


# --- Monitoring & learning --------------------------------------------------------------------------------

def test_monitoring_evaluation_learning(client, env, db):
    prog = make_programme(client, env)
    login(client, "field@hope.org")
    client.post(P(env, f"/{prog.id}/monitoring"), data={"what": "visit", "v-visit_date": date.today().isoformat(),
                                                        "v-purpose": "Check classroom attendance", "v-findings": "Good"})
    assert MonitoringVisit.query.count() == 1
    assert client.post(P(env, f"/{prog.id}/monitoring"), data={"what": "evaluation", "e-eval_type": "Baseline",
                                                               "e-title": "x", "e-status": "planned"}).status_code == 403
    as_(client, "meal")
    client.post(P(env, f"/{prog.id}/monitoring"), data={"what": "evaluation", "e-eval_type": "Mid-term",
                                                        "e-title": "Mid-term review", "e-status": "completed"})
    client.post(P(env, f"/{prog.id}/monitoring"), data={"what": "learning", "l-kind": "recommendation",
                                                        "l-title": "Train more female teachers",
                                                        "l-responsible_id": env["pd"].id})
    item = LearningItem.query.one()
    assert Notification.query.filter_by(user_id=env["pd"].id, kind="meal").count() == 1
    as_(client, "pd")
    client.post(P(env, f"/{prog.id}/learning/{item.id}/respond"), data={"response_status": "accepted",
                                                                        "management_response": "Budgeted for 2027"})
    db.session.expire_all()
    assert db.session.get(LearningItem, item.id).response_status == "accepted"


# --- Reports & exports --------------------------------------------------------------------------------------

def test_report_approval_freezes_figures_and_exports(client, env, db):
    prog = make_programme(client, env)
    login(client, "fin@hope.org")
    line = _line(client, env, prog, "Teacher workshops", "10000")
    e = _spend(client, env, prog, line, 2000)
    as_(client, "ed")
    client.post(P(env, f"/{prog.id}/finance/expenditure/{e.id}/approve"), data={})
    as_(client, "pd")
    r = client.post(P(env, f"/{prog.id}/reports/new"), data={
        "report_type": "quarterly", "title": "Q1 progress report", "period_start": f"{YEAR}-01-01",
        "period_end": f"{YEAR}-12-31", "summary": "Good start", "achievements": "Workshops held"})
    rep = ProgrammeReport.query.one()
    client.post(P(env, f"/{prog.id}/reports/{rep.id}/submit"), data={})
    r = client.post(P(env, f"/{prog.id}/reports/{rep.id}/approve"), data={}, follow_redirects=True)
    assert b"other than the author" in r.data
    as_(client, "ed")
    client.post(P(env, f"/{prog.id}/reports/{rep.id}/approve"), data={})
    db.session.expire_all()
    rep = db.session.get(ProgrammeReport, rep.id)
    assert rep.status == "approved" and rep.snapshot["finance"]["spent"] == 2000.0
    # New spending after approval does not change the approved report
    as_(client, "fin")
    e2 = _spend(client, env, prog, line, 3000, desc="Later spend")
    as_(client, "ed")
    client.post(P(env, f"/{prog.id}/finance/expenditure/{e2.id}/approve"), data={})
    html = client.get(P(env, f"/{prog.id}/reports/{rep.id}")).data.decode()
    assert "GHS 2,000.00" in html and "frozen" in html
    assert client.get(P(env, f"/{prog.id}/reports/{rep.id}/edit")).status_code == 302

    pdf = client.get(P(env, f"/{prog.id}/reports/{rep.id}/export.pdf"))
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and pdf.mimetype == "application/pdf"
    x = client.get(P(env, f"/{prog.id}/reports/{rep.id}/export.xlsx"))
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(x.data))
    assert wb.sheetnames == ["Summary", "Indicators", "Activities", "Budget", "Milestones"]
    assert any(row[0].value == "Spent (to date)" and row[1].value == 2000.0 for row in wb["Summary"].iter_rows())
    q = client.get(P(env, f"/{prog.id}/export.pdf?from={YEAR}-01-01&to={YEAR}-12-31"))
    assert q.data.startswith(b"%PDF")
    assert AuditLog.query.filter_by(action="report.exported").count() == 3


# --- Isolation, support, reminders, calendar, pages --------------------------------------------------------

def test_programme_isolation(client, app, env, db):
    prog = make_programme(client, env)
    prog2 = make_programme(client, env, title="Second programme")
    login(client, "meal@hope.org")
    ind2 = _indicator(client, env, prog2, name="Other indicator")
    login(client, "meal@hope.org")
    # an indicator of programme 2 cannot be reached through programme 1's URL
    assert client.get(P(env, f"/{prog.id}/indicators/{ind2.id}")).status_code == 404
    o2, _ = make_org("Rival Org", admin_email="admin@rival.org")
    other = app.test_client()
    login(other, "admin@rival.org")
    assert other.get(f"/o/{o2.slug}/programmes/{prog.id}").status_code == 404
    assert other.get(f"/o/{o2.slug}/programmes/{prog.id}/export.pdf").status_code == 404


def test_support_access_read_only(client, env, db):
    from app.models import PlatformRole, SupportAccessRequest, User, utcnow
    from tests.conftest import make_staff
    prog = make_programme(client, env)
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    req = SupportAccessRequest(organization_id=env["org"].id, reason="Checking a report problem",
                               requested_by_id=User.query.filter_by(email="support@holido.org").one().id,
                               duration_minutes=30, status="approved", starts_at=utcnow(),
                               expires_at=utcnow() + timedelta(minutes=30))
    db.session.add(req)
    db.session.commit()
    login(client, "support@holido.org")
    client.post(f"/platform/support/{req.id}/enter")
    assert client.get(P(env, f"/{prog.id}")).status_code == 200
    assert client.get(P(env, f"/{prog.id}/finance")).status_code == 200
    assert client.post(P(env, f"/{prog.id}/status"), data={"status": "planned"}).status_code == 403


def test_reminders_and_calendar(client, app, env, db):
    prog = make_programme(client, env)
    db.session.add(Milestone(organization_id=env["org"].id, programme_id=prog.id, title="Mid-term review",
                             due_date=date.today() + timedelta(days=3)))
    db.session.add(Activity(organization_id=env["org"].id, programme_id=prog.id, title="Community meeting",
                            planned_start=date.today() + timedelta(days=1), responsible_id=env["field"].id))
    db.session.commit()
    runner = app.test_cli_runner()
    runner.invoke(args=["oims", "send-reminders"])
    runner.invoke(args=["oims", "send-reminders"])
    assert Notification.query.filter_by(user_id=env["pd"].id, kind="reminder").count() == 1
    assert Notification.query.filter_by(user_id=env["field"].id, kind="reminder").count() == 1
    login(client, "field@hope.org")
    d = date.today() + timedelta(days=1)
    html = client.get(f"/o/{env['org'].slug}/calendar?month={d:%Y-%m}").data.decode()
    assert "Activity: Community meeting" in html


def test_all_programme_pages_render(client, env, db):
    prog = make_programme(client, env)
    as_(client, "fin")
    line = _line(client, env, prog, "Workshops", "1000")
    ind = _indicator(client, env, prog)
    as_(client, "admin")
    client.post(P(env, f"/{prog.id}/activities/new"), data={"title": "A1", "planned_start": date.today().isoformat(),
                                                            "planned_end": date.today().isoformat(), "planned_budget": "0",
                                                            "budget_line_id": line.id})
    act = Activity.query.one()
    client.post(P(env, f"/{prog.id}/reports/new"), data={"report_type": "monthly", "title": "M1",
                                                         "period_start": f"{YEAR}-01-01", "period_end": f"{YEAR}-01-31"})
    rep = ProgrammeReport.query.one()
    from app.models import Evaluation
    db.session.add(Evaluation(organization_id=env["org"].id, programme_id=prog.id, eval_type="Final", title="Final eval"))
    db.session.commit()
    ev = Evaluation.query.one()
    for path in ("/", "/new", f"/{prog.id}", f"/{prog.id}/edit", f"/{prog.id}/planning", f"/{prog.id}/team",
                 f"/{prog.id}/results", f"/{prog.id}/indicators", f"/{prog.id}/indicators/new",
                 f"/{prog.id}/indicators/{ind.id}", f"/{prog.id}/indicators/{ind.id}/edit", f"/{prog.id}/workplans",
                 f"/{prog.id}/activities/new", f"/{prog.id}/activities/{act.id}", f"/{prog.id}/activities/{act.id}/edit",
                 f"/{prog.id}/finance", f"/{prog.id}/monitoring", f"/{prog.id}/evaluations/{ev.id}/edit",
                 f"/{prog.id}/reports", f"/{prog.id}/reports/new", f"/{prog.id}/reports/{rep.id}",
                 f"/{prog.id}/reports/{rep.id}/edit"):
        assert client.get(P(env, path)).status_code == 200, path
    assert client.get(f"/o/{env['org'].slug}/registers/").status_code == 200
    as_(client, "auditor")
    for path in (f"/{prog.id}", f"/{prog.id}/finance", f"/{prog.id}/indicators", f"/{prog.id}/reports"):
        assert client.get(P(env, path)).status_code == 200, path
    assert client.post(P(env, f"/{prog.id}/planning"), data={"strategy": "x"}).status_code == 403



