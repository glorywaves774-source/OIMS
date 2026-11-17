"""Starter plans, the public pricing section and plan choice on registration."""
from decimal import Decimal

from app.models import SubscriptionPlan
from app.plans import STARTER_PLANS, add_starter_plans


def test_starter_plans_added_once_and_existing_plans_untouched(db):
    db.session.add(SubscriptionPlan(code="standard", name="Our Standard", currency="GHS",
                                    monthly_price=Decimal("1234"), annual_price=Decimal("0")))
    db.session.commit()
    added = add_starter_plans()
    db.session.commit()
    assert added == ["Starter", "Professional", "Enterprise"]
    mine = SubscriptionPlan.query.filter_by(code="standard").one()
    assert mine.name == "Our Standard" and mine.monthly_price == Decimal("1234")
    assert add_starter_plans() == []
    assert SubscriptionPlan.query.count() == 4


def test_starter_plan_values_are_sensible():
    codes = [p["code"] for p in STARTER_PLANS]
    assert len(codes) == len(set(codes))
    public = [p for p in STARTER_PLANS if p["is_public"]]
    prices = [p["monthly_price"] for p in public]
    assert prices == sorted(prices) and all(x > 0 for x in prices)
    for p in STARTER_PLANS:
        assert p["annual_price"] <= p["monthly_price"] * 12        # paying yearly never costs more
        assert len(p["description"]) <= 500
    enterprise = next(p for p in STARTER_PLANS if p["code"] == "enterprise")
    assert not enterprise["is_public"] and enterprise["max_users"] is None


def test_cli_adds_missing_plans(app, db):
    runner = app.test_cli_runner()
    r = runner.invoke(args=["oims", "starter-plans"])
    assert "Added: Starter, Standard, Professional, Enterprise" in r.output
    r = runner.invoke(args=["oims", "starter-plans"])
    assert "nothing changed" in r.output


def test_public_page_shows_public_plans_only(client, db):
    add_starter_plans()
    retired = SubscriptionPlan(code="old", name="Old Plan", currency="GHS", monthly_price=Decimal("10"),
                               annual_price=Decimal("0"), is_active=False)
    db.session.add(retired)
    db.session.commit()
    html = client.get("/").get_data(as_text=True)
    assert "Plans and pricing" in html
    assert "GHS 350" in html and "GHS 900" in html and "GHS 2,200" in html
    assert "or GHS 9,000 a year" in html
    assert "Up to 30 users" in html and "25 GB of documents" in html and "14-day free trial" in html
    assert "Enterprise</h3>" not in html and "Old Plan" not in html
    std = SubscriptionPlan.query.filter_by(code="standard").one()
    assert f"/register?plan={std.id}" in html


def test_no_pricing_section_without_plans(client, db):
    assert "Plans and pricing" not in client.get("/").get_data(as_text=True)


def test_register_lists_prices_and_preselects_the_chosen_plan(client, db):
    add_starter_plans()
    db.session.commit()
    std = SubscriptionPlan.query.filter_by(code="standard").one()
    ent = SubscriptionPlan.query.filter_by(code="enterprise").one()
    html = client.get(f"/register?plan={std.id}").get_data(as_text=True)
    assert f'<option selected value="{std.id}">Standard · GHS 900 a month</option>' in html
    assert "Enterprise" not in html
    html = client.get(f"/register?plan={ent.id}").get_data(as_text=True)   # private plans cannot be chosen
    assert "selected" not in html.split('id="plan_id"', 1)[1].split("</select>", 1)[0]


def test_edited_plan_shows_new_price(client, db):
    add_starter_plans()
    db.session.commit()
    p = SubscriptionPlan.query.filter_by(code="starter").one()
    p.monthly_price = Decimal("499.50")
    p.name = "Basic"
    db.session.commit()
    html = client.get("/").get_data(as_text=True)
    assert "GHS 499.50" in html and "Basic" in html


def test_pricing_in_french(client, db):
    add_starter_plans()
    db.session.commit()
    client.post("/language", data={"lang": "fr", "next": "/"})
    html = client.get("/").get_data(as_text=True)
    assert "Formules et tarifs" in html
    assert "Jusqu'à 30 utilisateurs" in html or "Jusqu&#39;à 30 utilisateurs" in html
    assert "Essai gratuit de 14 jours" in html
    assert "par mois" in html
    assert ">Standard</h3>" in html                                           # plan names are not translated
