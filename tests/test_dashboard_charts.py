"""Charts on the dashboards: shown with the right figures, and only to people allowed to see them."""
from datetime import date
from decimal import Decimal

from app.extensions import db as _db
from app.models import BudgetCategory, BudgetLine, Expenditure, Programme, Task
from app.tenancy import clear_tenant, set_tenant
from tests.conftest import add_member, login, logout, make_department, make_org, make_staff, make_staff_profile


def setup_org():
    org, admin = make_org("Chart Trust", admin_email="admin@chart.org")
    staff_user, _ = add_member(org, "staff@chart.org", "Staff Member")
    dept = make_department(org, "Finance")
    make_staff_profile(org, admin, department=dept)
    make_staff_profile(org, staff_user, department=dept)
    set_tenant(org.id)
    cat = BudgetCategory.query.first()
    prog = Programme(organization_id=org.id, code="PRG-1", title="Education", currency=org.currency, status="active")
    _db.session.add(prog); _db.session.flush()
    line = BudgetLine(organization_id=org.id, category_id=cat.id, description="Line", amount=Decimal(1000),
                      programme_id=prog.id)
    _db.session.add(line); _db.session.flush()
    _db.session.add(Expenditure(organization_id=org.id, budget_line_id=line.id, programme_id=prog.id,
                                spent_on=date.today(), description="Spent", amount=Decimal(250),
                                kind="expenditure", status="approved"))
    _db.session.add(Task(organization_id=org.id, title="Write report", status="todo", assigned_to_id=staff_user.id))
    _db.session.commit()
    clear_tenant()
    return org


def test_workspace_dashboard_charts_follow_permissions(client, db):
    org = setup_org()
    login(client, "admin@chart.org")
    page = client.get(f"/o/{org.slug}/").get_data(as_text=True)
    assert "Budget used (%)" in page and "PRG-1: 25%" in page            # 250 of 1,000 spent
    assert "Staff by department" in page and "Finance: 2" in page
    logout(client)
    login(client, "staff@chart.org")
    page = client.get(f"/o/{org.slug}/").get_data(as_text=True)
    assert "My open tasks" in page and "To do: 1" in page
    assert "Budget used (%)" not in page                                  # no finance access
    assert "PRG-1" not in page


def test_finance_and_meal_dashboard_charts(client, db):
    org = setup_org()
    login(client, "admin@chart.org")
    page = client.get(f"/o/{org.slug}/finance/").get_data(as_text=True)
    assert "Approved spending per month" in page and "Budget used (%)" in page
    page = client.get(f"/o/{org.slug}/meal/").get_data(as_text=True)
    assert page.count('class="chart"') == 0 or "Active beneficiaries by sex" in page   # charts only with data


def test_platform_dashboard_charts(client, db):
    setup_org()
    make_staff("super@chart-platform.org")
    login(client, "super@chart-platform.org")
    page = client.get("/platform/").get_data(as_text=True)
    assert "Organizations by status" in page and "Active: 1" in page
    assert "New organizations per month" in page


def test_chart_titles_in_french(client, db):
    org = setup_org()
    login(client, "admin@chart.org")
    client.post("/language", data={"lang": "fr", "next": "/"})
    page = client.get(f"/o/{org.slug}/").get_data(as_text=True)
    assert "Budget utilisé (%)" in page and "Personnel par département" in page
    # the department is a record: its name stays as typed, in the label and in the hover tip
    assert 'data-tip="Finance: 2"' in page and 'data-tip="Finances' not in page
    assert '<span class="hbar-label" translate="no">Finance</span>' in page
