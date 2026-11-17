"""Starter subscription plans (Starter, Standard, Professional, Enterprise).

Added only when no plan exists yet, so plans Kayron has already made or edited are never touched.
Prices and limits are placeholders to edit in the Kayron console (Plans).

Revision ID: c8e2a4f6b1d3
Revises: b5d1f3a7c9e2
"""
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "c8e2a4f6b1d3"
down_revision = "b5d1f3a7c9e2"
branch_labels = None
depends_on = None

GB = 1024
PLANS = [  # frozen copy of app/plans.py at the time of this update
    ("starter", "Starter", "For small offices, schools and community groups getting started.",
     350, 3500, 14, 10, 5 * GB, True),
    ("standard", "Standard", "For growing NGOs, churches and businesses with several departments and projects.",
     900, 9000, 14, 30, 25 * GB, True),
    ("professional", "Professional", "For larger organizations running many programmes, projects and donors.",
     2200, 22000, 14, 100, 100 * GB, True),
    ("enterprise", "Enterprise", "For networks and large institutions. Price agreed with Kayron; assigned by Kayron only.",
     5000, 50000, 0, None, None, False),
]


def upgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT count(*) FROM subscription_plans")).scalar():
        return
    plans = sa.table("subscription_plans", sa.column("code"), sa.column("name"), sa.column("description"),
                     sa.column("currency"), sa.column("monthly_price"), sa.column("annual_price"),
                     sa.column("trial_days"), sa.column("max_users"), sa.column("max_storage_mb"),
                     sa.column("is_public"), sa.column("is_active"), sa.column("created_at"),
                     sa.column("updated_at"))
    now = datetime.now(timezone.utc)
    op.bulk_insert(plans, [dict(code=c, name=n, description=d, currency="GHS", monthly_price=m, annual_price=a,
                                trial_days=t, max_users=u, max_storage_mb=s, is_public=p, is_active=True,
                                created_at=now, updated_at=now)
                           for (c, n, d, m, a, t, u, s, p) in PLANS])


def downgrade():
    # Plans may be in use or edited by now; they are left in place.
    pass
