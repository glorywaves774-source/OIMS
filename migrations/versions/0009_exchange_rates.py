"""Exchange rates entered by each organization's finance team.

Revision ID: a3c7e9f1b2d4
Revises: 9e1a3c5b7d42
"""
from alembic import op
import sqlalchemy as sa

revision = "a3c7e9f1b2d4"
down_revision = "9e1a3c5b7d42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exchange_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        sa.Column("source", sa.String(200)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "currency", "base_currency", "effective_on",
                            name="uq_exchange_rates_pair_day"),
    )
    op.create_index("ix_exchange_rates_organization_id", "exchange_rates", ["organization_id"])
    op.create_index("ix_exchange_rates_effective_on", "exchange_rates", ["effective_on"])


def downgrade():
    op.drop_index("ix_exchange_rates_effective_on", table_name="exchange_rates")
    op.drop_index("ix_exchange_rates_organization_id", table_name="exchange_rates")
    op.drop_table("exchange_rates")
