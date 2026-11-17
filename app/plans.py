"""Starter subscription plans. Prices and limits are placeholders for Kayron to edit in the
Kayron console (Plans). Adding them never changes or removes a plan that already exists."""
from decimal import Decimal

from app.models import SubscriptionPlan, db

STARTER_PLANS = (
    dict(code="starter", name="Starter", currency="GHS", monthly_price=Decimal("350"), annual_price=Decimal("3500"),
         trial_days=14, max_users=10, max_storage_mb=5 * 1024, is_public=True,
         description="For small offices, schools and community groups getting started."),
    dict(code="standard", name="Standard", currency="GHS", monthly_price=Decimal("900"), annual_price=Decimal("9000"),
         trial_days=14, max_users=30, max_storage_mb=25 * 1024, is_public=True,
         description="For growing NGOs, churches and businesses with several departments and projects."),
    dict(code="professional", name="Professional", currency="GHS", monthly_price=Decimal("2200"),
         annual_price=Decimal("22000"), trial_days=14, max_users=100, max_storage_mb=100 * 1024, is_public=True,
         description="For larger organizations running many programmes, projects and donors."),
    dict(code="enterprise", name="Enterprise", currency="GHS", monthly_price=Decimal("5000"),
         annual_price=Decimal("50000"), trial_days=0, max_users=None, max_storage_mb=None, is_public=False,
         description="For networks and large institutions. Price agreed with Kayron; assigned by Kayron only."),
)


def add_starter_plans():
    """Add any starter plan whose code is not used yet. Returns the names added."""
    used = {c for (c,) in db.session.query(SubscriptionPlan.code)}
    added = []
    for spec in STARTER_PLANS:
        if spec["code"] not in used:
            db.session.add(SubscriptionPlan(is_active=True, **spec))
            added.append(spec["name"])
    return added
