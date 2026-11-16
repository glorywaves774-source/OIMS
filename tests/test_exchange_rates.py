"""Exchange rates: entering them, converting with them, and combined totals."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db as _db
from app.models import BudgetCategory, BudgetLine, ExchangeRate, Expenditure, Programme, Project
from app.tenancy import clear_tenant, set_tenant
from tests.conftest import add_member, login, logout, make_org

TODAY = date.today()


@pytest.fixture
def env(app, db):
    org, admin = make_org("Rate Trust", admin_email="admin@rate.org")   # main currency GHS
    fin, _ = add_member(org, "fin@rate.org", "Finance Officer")
    po, _ = add_member(org, "po@rate.org", "Programme Officer")
    clear_tenant()
    return {"org": org, "W": lambda p: f"/o/{org.slug}{p}"}


def add_rate(client, env, cur, rate, on=TODAY, source="Bank of Ghana"):
    return client.post(env["W"]("/finance/rates"), data={"currency": cur, "rate": rate, "effective_on": on.isoformat(),
                                                         "source": source})


def money(env):
    """A GHS programme with a USD project and a EUR project: budgets and approved spending."""
    org = env["org"]
    set_tenant(org.id)
    cat = BudgetCategory.query.first()
    prog = Programme(organization_id=org.id, code="PRG-1", title="Education", currency="GHS", status="active")
    _db.session.add(prog); _db.session.flush()
    usd = Project(organization_id=org.id, code="PRJ-USD", title="Water", currency="USD", programme_id=prog.id,
                  status="active")
    eur = Project(organization_id=org.id, code="PRJ-EUR", title="Health", currency="EUR", programme_id=prog.id,
                  status="active")
    _db.session.add_all([usd, eur]); _db.session.flush()
    lines = {}
    for owner, amount in ((prog, "1000"), (usd, "100"), (eur, "50")):
        bl = BudgetLine(organization_id=org.id, category_id=cat.id, description="Line", amount=Decimal(amount),
                        **{owner.fk: owner.id})
        _db.session.add(bl); _db.session.flush()
        lines[owner.code] = bl
    for owner, amount, day in ((prog, "200", TODAY), (usd, "10", TODAY - timedelta(days=40)), (usd, "10", TODAY)):
        _db.session.add(Expenditure(organization_id=org.id, budget_line_id=lines[owner.code].id, spent_on=day,
                                    description="Spent", amount=Decimal(amount), kind="expenditure",
                                    status="approved", **{owner.fk: owner.id}))
    _db.session.commit()
    clear_tenant()
    return prog, usd, eur


def test_rates_page_and_who_may_change_rates(client, env):
    login(client, "fin@rate.org")
    page = client.get(env["W"]("/finance/rates")).get_data(as_text=True)
    assert "Add a rate" in page and "No rates entered yet" in page
    r = add_rate(client, env, "USD", "15.4")
    assert r.status_code == 302
    page = client.get(env["W"]("/finance/rates")).get_data(as_text=True)
    assert "1 USD = 15.4 GHS" in page and "Bank of Ghana" in page
    # same currency and day twice is refused; future dates and nonsense rates too
    assert "already a rate" in add_rate(client, env, "USD", "16").get_data(as_text=True)
    assert "today at the latest" in add_rate(client, env, "USD", "16", on=TODAY + timedelta(days=1)).get_data(as_text=True)
    assert "positive rate" in add_rate(client, env, "EUR", "-2").get_data(as_text=True)
    assert ExchangeRate.query.count() == 1
    # the main currency cannot be given a rate against itself
    assert '<option value="GHS"' not in client.get(env["W"]("/finance/rates")).get_data(as_text=True)
    logout(client)
    # a Programme Officer may see rates (finance view) but not change them
    login(client, "po@rate.org")
    page = client.get(env["W"]("/finance/rates"))
    assert page.status_code in (200, 403)
    assert "Add a rate" not in page.get_data(as_text=True)
    assert add_rate(client, env, "EUR", "17").status_code == 403
    rid = ExchangeRate.query.first().id
    assert client.post(env["W"](f"/finance/rates/{rid}/delete")).status_code == 403
    logout(client)
    login(client, "fin@rate.org")
    assert client.post(env["W"](f"/finance/rates/{rid}/delete")).status_code == 302
    assert ExchangeRate.query.count() == 0
    from app.models import AuditLog
    actions = {a.action for a in AuditLog.query.all()}
    assert {"exchange_rate.added", "exchange_rate.removed"} <= actions


def test_rate_lookup_rules(app, env):
    from app.fx import Rates, combine
    org = env["org"]
    set_tenant(org.id)
    for cur, rate, day in (("USD", "15", TODAY - timedelta(days=30)), ("USD", "16", TODAY - timedelta(days=5)),
                           ("EUR", "17", TODAY - timedelta(days=5))):
        _db.session.add(ExchangeRate(organization_id=org.id, currency=cur, base_currency="GHS", rate=Decimal(rate),
                                     effective_on=day))
    _db.session.commit()
    fx = Rates(org.id)
    assert fx.rate("GHS", "GHS") == 1
    assert fx.rate("USD", "GHS") == 16                                    # latest
    assert fx.rate("USD", "GHS", TODAY - timedelta(days=10)) == 15        # the rate on that day
    assert fx.rate("USD", "GHS", TODAY - timedelta(days=31)) is None      # before any rate: never guessed
    assert fx.convert(100, "GHS", "USD") == Decimal("6.25")               # the other way round
    assert fx.convert(100, "USD", "EUR") == Decimal("94.12")              # through GHS: 100*16/17
    assert fx.rate("KES", "GHS") is None
    combined, missing = combine({"GHS": {"b": Decimal(10)}, "USD": {"b": Decimal(1)}, "KES": {"b": Decimal(5)}},
                                "GHS", fx)
    assert combined == {"b": Decimal("26.00")} and missing == ["KES"]
    clear_tenant()


def test_rates_belong_to_one_organization(client, env):
    other, _ = make_org("Other Trust", admin_email="admin@other.org")
    clear_tenant()
    login(client, "admin@other.org")
    add_rate(client, {"W": lambda p: f"/o/{other.slug}{p}"}, "USD", "99")
    logout(client)
    login(client, "fin@rate.org")
    page = client.get(env["W"]("/finance/rates")).get_data(as_text=True)
    assert "99" not in page and "No rates entered yet" in page
    rid = _db.session.execute(_db.select(ExchangeRate.id)).scalar()
    assert client.post(env["W"](f"/finance/rates/{rid}/delete")).status_code == 404


def test_combined_totals_on_finance_overview_and_programme(client, env):
    prog, usd, eur = money(env)
    login(client, "fin@rate.org")
    page = client.get(env["W"]("/finance/")).get_data(as_text=True)
    assert "All together in GHS" in page
    assert "EUR, USD are not included" in page or "are not included" in page
    add_rate(client, env, "USD", "15")
    page = client.get(env["W"]("/finance/")).get_data(as_text=True)
    # budget 1000 GHS + 100 USD x 15 = 2500 GHS; EUR still missing
    assert "2,500.00" in page and "EUR is not included" in page
    add_rate(client, env, "EUR", "17")
    page = client.get(env["W"]("/finance/")).get_data(as_text=True)
    assert "3,350.00" in page and "not included" not in page            # + 50 EUR x 17 = 850
    # Programme roll-up now includes the projects, converted
    from app.programme_logic import consolidated
    set_tenant(env["org"].id)
    from flask import g
    g.tenant = env["org"]
    cons = consolidated(_db.session.get(Programme, prog.id))
    clear_tenant()
    assert cons["budget"] == Decimal("3350.00") and cons["missing"] == []
    assert cons["spent"] == Decimal("200") + Decimal("20") * 15


def test_budget_report_converts_spending_at_each_days_rate(client, env):
    money(env)
    login(client, "fin@rate.org")
    add_rate(client, env, "USD", "10", on=TODAY - timedelta(days=60))
    add_rate(client, env, "USD", "20", on=TODAY - timedelta(days=1))
    start = (TODAY - timedelta(days=90)).isoformat()
    page = client.get(env["W"](f"/reports/budget?start={start}&end={TODAY.isoformat()}")).get_data(as_text=True)
    assert "all together (GHS)" in page
    # spent in the period: 200 GHS + 10 USD x 10 (40 days ago) + 10 USD x 20 (today) = 500 GHS
    assert "500.00" in page
    assert "rate of the day of each payment" in page
    assert "Not included (no exchange rate yet): EUR" in page
