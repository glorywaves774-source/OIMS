"""Phase 7: organization reports — permissions, figures without double counting, filters and exports."""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import (AuditLog, Beneficiary, BudgetCategory, BudgetLine, ConsentRecord, Enrollment, Expenditure,
                        Feedback, Indicator, IndicatorResult, Programme, Project)
from tests.conftest import add_member, login, logout, make_department, make_org, make_staff_profile

YEAR = date.today().year
TODAY = date.today()


@pytest.fixture
def env(app, db):
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    dept = make_department(o, "Programmes")
    other_dept = make_department(o, "Finance")
    people = {"org": o, "dept": dept, "admin": admin}
    for key, role, d in [("pd", "Programme Director", dept), ("fin", "Finance Officer", other_dept),
                         ("field", "Field Officer", dept), ("meal", "MEAL Officer", None),
                         ("sg", "Safeguarding Focal Point", None), ("staff", "Staff Member", dept),
                         ("head", "Department Head", dept), ("hr", "HR Officer", other_dept),
                         ("auditor", "Read-only / Auditor", None)]:
        u, _ = add_member(o, f"{key}@hope.org", role_name=role)
        people[key] = u
        make_staff_profile(o, u, department=d)
    return people


def W(env, path):
    return f"/o/{env['org'].slug}/reports{path}"


def as_(client, key):
    logout(client)
    login(client, f"{key}@hope.org")


@pytest.fixture
def data(client, env, db):
    as_(client, "pd")
    client.post(f"/o/{env['org'].slug}/programmes/new", data={"title": "=HYPERLINK(\"http://x\")", "currency": "GHS",
                                                               "approved_budget": "0", "manager_id": env["pd"].id,
                                                               "department_id": env["dept"].id,
                                                               "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR}-12-31"})
    prog = Programme.query.one()
    client.post(f"/o/{env['org'].slug}/projects/new", data={"title": "School Water", "currency": "GHS",
                                                             "approved_budget": "0", "manager_id": env["pd"].id,
                                                             "programme_id": prog.id})
    proj = Project.query.one()
    other = Programme(organization_id=env["org"].id, code="PRG/X/9", title="Not mine", currency="GHS",
                      approved_budget=0, status="active")
    db.session.add(other)
    db.session.flush()
    client.post(f"/o/{env['org'].slug}/programmes/{prog.id}/team", data={"user_id": env["field"].id})
    cat = BudgetCategory.query.filter_by(organization_id=env["org"].id).first()
    lines = {}
    for owner, amt in ((prog, "1000"), (proj, "500"), (other, "700")):
        line = BudgetLine(organization_id=env["org"].id, category_id=cat.id, description=f"Line {owner.code}",
                          amount=Decimal(amt), original_amount=Decimal(amt), **{owner.fk: owner.id})
        db.session.add(line)
        db.session.flush()
        lines[owner.code] = line
    for owner, amt, when in ((prog, "300", TODAY), (prog, "100", date(YEAR - 1, 6, 1)), (proj, "50", TODAY),
                             (other, "70", TODAY)):
        db.session.add(Expenditure(organization_id=env["org"].id, budget_line_id=lines[owner.code].id, kind="expenditure",
                                   spent_on=when, description="Spend", amount=Decimal(amt), status="approved",
                                   **{owner.fk: owner.id}))
    db.session.commit()
    logout(client)
    return prog, proj, other


def test_catalogue_follows_permissions(client, env, db, data):
    as_(client, "staff")   # sees only the assets in their care
    html = client.get(W(env, "/")).data.decode()
    assert "Assets" in html and "Budget and spending" not in html
    assert client.get(W(env, "/budget")).status_code == 403
    assert client.get(W(env, "/nope")).status_code == 404
    as_(client, "fin")
    html = client.get(W(env, "/")).data.decode()
    assert "Budget and spending" in html and "Donor funding" in html and "Beneficiaries reached" not in html
    as_(client, "auditor")
    html = client.get(W(env, "/")).data.decode()
    for title in ("Portfolio summary", "Budget and spending", "Beneficiaries reached", "Feedback and complaints"):
        assert title in html


def test_budget_report_counts_each_amount_once(client, env, db, data):
    prog, proj, other = data
    as_(client, "fin")
    html = client.get(W(env, "/budget")).data.decode()
    assert "GHS" in html and "Approved spending per month" in html
    r = client.get(W(env, "/budget.csv?table=owners"))
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    head = rows[0]
    by_code = {row[0]: dict(zip(head, row)) for row in rows[1:]}
    assert by_code[prog.code]["Spent in the period"] == "300.0" and by_code[prog.code]["Spent to date"] == "400.0"
    assert by_code[proj.code]["Spent to date"] == "50.0"
    assert sum(float(v["Budget"]) for v in by_code.values()) == 2200.0   # 1000 + 500 + 700, nothing twice
    assert AuditLog.query.filter_by(action="report.exported").count() == 1
    # filtering by the programme includes its project, or not
    r = client.get(W(env, f"/budget.csv?table=owners&owner=programme:{prog.id}"))
    codes = {row[0] for row in csv.reader(io.StringIO(r.data.decode("utf-8-sig")))}
    assert prog.code in codes and proj.code in codes and other.code not in codes
    r = client.get(W(env, f"/budget.csv?table=owners&owner=programme:{prog.id}&projects=0"))
    codes = {row[0] for row in csv.reader(io.StringIO(r.data.decode("utf-8-sig")))}
    assert proj.code not in codes
    # a period without spending
    r = client.get(W(env, f"/budget.csv?table=owners&from={YEAR - 1}-01-01&to={YEAR - 1}-12-31"))
    rows = list(csv.reader(io.StringIO(r.data.decode("utf-8-sig"))))
    assert dict(zip(rows[0], [r for r in rows[1:] if r[0] == prog.code][0]))["Spent in the period"] == "100.0"


def test_exports_are_safe_and_complete(client, env, db, data):
    import openpyxl
    prog, proj, other = data
    as_(client, "pd")
    r = client.get(W(env, "/portfolio.csv"))
    text = r.data.decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "\n=HYPERLINK" not in text and ",=HYPERLINK" not in text
    x = client.get(W(env, "/portfolio.xlsx"))
    wb = openpyxl.load_workbook(io.BytesIO(x.data))
    assert wb.sheetnames[0] == "Summary" and "Programmes and projects" in wb.sheetnames
    titles = [c.value for c in wb["Programmes and projects"]["B"]]
    assert any(isinstance(t, str) and t.startswith("'=HYPERLINK") for t in titles)
    p = client.get(W(env, "/portfolio.pdf"))
    assert p.data.startswith(b"%PDF") and p.mimetype == "application/pdf"
    # the older programme report export is protected too
    x = client.get(f"/o/{env['org'].slug}/programmes/{prog.id}/export.xlsx")
    wb = openpyxl.load_workbook(io.BytesIO(x.data))
    vals = [c.value for row in wb["Summary"].iter_rows() for c in row if isinstance(c.value, str)]
    assert vals and not any(v.startswith("=") for v in vals)
    from app.analytics_export import safe_row
    assert safe_row(["=1+1", "+cmd", "-2", "@x", "ok", 5]) == ["'=1+1", "'+cmd", "'-2", "'@x", "ok", 5]


def test_reports_respect_scope(client, env, db, data):
    prog, proj, other = data
    as_(client, "field")   # on the programme team only
    html = client.get(W(env, "/portfolio")).data.decode()
    assert prog.code in html and other.code not in html
    assert client.get(W(env, "/budget")).status_code == 403
    assert client.get(W(env, f"/portfolio?owner=programme:{other.id}")).status_code == 404
    assert client.get(W(env, "/portfolio?from=not-a-date")).status_code == 400
    o2, _ = make_org("Rival Org", admin_email="admin@rival.org")
    other_client = client.application.test_client()
    login(other_client, "admin@rival.org")
    assert other_client.get(f"/o/{o2.slug}/reports/portfolio?owner=programme:{prog.id}").status_code == 404
    assert prog.code.encode() not in other_client.get(f"/o/{o2.slug}/reports/portfolio").data


def _person(env, db, first, sex, owner, birth):
    b = Beneficiary(organization_id=env["org"].id, code=f"BEN/T/{first}", first_name=first, last_name="Test", sex=sex,
                    birth_year=birth, registered_on=TODAY)
    db.session.add(b)
    db.session.flush()
    db.session.add(ConsentRecord(organization_id=env["org"].id, beneficiary_id=b.id, given_on=TODAY, given_by="self",
                                 purposes=["services"], method="written"))
    for o in owner:
        db.session.add(Enrollment(organization_id=env["org"].id, beneficiary_id=b.id, enrolled_on=TODAY,
                                  **{o.fk: o.id}))
    return b


def test_beneficiary_report_counts_people_once(client, env, db, data):
    prog, proj, other = data
    _person(env, db, "Ama", "female", [prog, proj], YEAR - 12)    # in both: counted once
    _person(env, db, "Kofi", "male", [proj], YEAR - 30)
    _person(env, db, "Esi", "female", [other], YEAR - 70)
    db.session.commit()
    as_(client, "meal")
    rows = list(csv.reader(io.StringIO(client.get(W(env, "/beneficiaries.csv?table=owners")).data.decode("utf-8-sig"))))
    by = {r[0]: r for r in rows[1:]}
    assert by[prog.code][2] == "1" and by[proj.code][2] == "2" and by[other.code][2] == "1"
    total = [r for r in rows if r[1] == "All, each person once"][0]
    assert total[2] == "3" and total[3] == "2" and total[4] == "1"      # not 4: Ama counted once
    html = client.get(W(env, "/beneficiaries")).data.decode()
    assert "People reached by age group" in html and "6-14 years" in html


def test_feedback_report_keeps_sensitive_cases_confidential(client, env, db, data):
    for i, (cat, sens) in enumerate((("complaint", False), ("question", False), ("safeguarding", True))):
        db.session.add(Feedback(organization_id=env["org"].id, code=f"FB/T/{i}", category=cat, sensitive=sens,
                                received_on=TODAY - timedelta(days=5), summary=f"Case {i}", description="Details",
                                status="closed" if i == 0 else "new", responded_on=TODAY - timedelta(days=2) if i == 0
                                else None, satisfaction="satisfied" if i == 0 else None, due_date=TODAY + timedelta(days=2)))
    db.session.commit()
    as_(client, "meal")
    html = client.get(W(env, "/feedback")).data.decode()
    assert "Sensitive cases (safeguarding, fraud, misconduct) received in the period: 1" in html
    assert "left out of the figures above" in html
    rows = list(csv.reader(io.StringIO(client.get(W(env, "/feedback.csv?table=types")).data.decode("utf-8-sig"))))
    counts = {r[0]: r[1] for r in rows[1:]}
    assert counts["Safeguarding concern"] == "0" and counts["Complaint about a service"] == "1"
    as_(client, "sg")
    rows = list(csv.reader(io.StringIO(client.get(W(env, "/feedback.csv?table=types")).data.decode("utf-8-sig"))))
    assert {r[0]: r[1] for r in rows[1:]}["Safeguarding concern"] == "1"


def test_indicator_status(client, env, db, data):
    prog, proj, other = data
    done = Indicator(organization_id=env["org"].id, programme_id=prog.id, code="1", name="Wells built", unit="number",
                     aggregation="sum", baseline_value=0, target_value=10)
    empty = Indicator(organization_id=env["org"].id, programme_id=prog.id, code="2", name="Girls enrolled",
                      unit="number", aggregation="sum", baseline_value=0, target_value=100)
    db.session.add_all([done, empty])
    db.session.flush()
    db.session.add(IndicatorResult(organization_id=env["org"].id, indicator_id=done.id, period_start=date(YEAR, 1, 1),
                                   period_end=date(YEAR, 1, 31), value=10, status="verified"))
    db.session.add(IndicatorResult(organization_id=env["org"].id, indicator_id=empty.id, period_start=date(YEAR, 1, 1),
                                   period_end=date(YEAR, 1, 31), value=60, status="submitted"))  # not checked yet
    db.session.commit()
    as_(client, "meal")
    rows = list(csv.reader(io.StringIO(client.get(W(env, "/indicators.csv")).data.decode("utf-8-sig"))))
    status = {r[2]: r[-1] for r in rows[1:]}
    assert status == {"Wells built": "Achieved", "Girls enrolled": "No data yet"}


def test_staff_report_by_department_scope(client, env, db, data):
    as_(client, "hr")   # organization-wide HR records
    rows = list(csv.reader(io.StringIO(client.get(W(env, "/staff.csv?table=departments")).data.decode("utf-8-sig"))))
    depts = {r[0]: r[1] for r in rows[1:]}
    assert depts["Programmes"] == "4" and depts["Finance"] == "2"
    as_(client, "head")  # department head: only their department
    rows = list(csv.reader(io.StringIO(client.get(W(env, "/staff.csv?table=departments")).data.decode("utf-8-sig"))))
    assert {r[0] for r in rows[1:]} == {"Programmes"}


def test_every_report_renders_and_exports(client, env, db, data):
    as_(client, "admin")
    from app.analytics import REPORTS
    for key in REPORTS:
        assert client.get(W(env, f"/{key}")).status_code == 200, key
        for fmt in ("csv", "xlsx", "pdf"):
            r = client.get(W(env, f"/{key}.{fmt}?from={YEAR}-01-01&to={TODAY.isoformat()}"))
            assert r.status_code == 200 and len(r.data) > 20, (key, fmt)
    assert client.get(W(env, "/")).status_code == 200
    # an empty organization renders too
    o2, _ = make_org("Empty Org", admin_email="admin@empty.org")
    c2 = client.application.test_client()
    login(c2, "admin@empty.org")
    for key in REPORTS:
        assert c2.get(f"/o/{o2.slug}/reports/{key}").status_code == 200, key
