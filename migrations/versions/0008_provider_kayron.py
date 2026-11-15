"""Provider is now Kayron Global Tech Services.

Updates the billing settings company name only if it still has the old default, so a name that
was already customised is left alone. Invoices already issued keep the issuer frozen on them.

Revision ID: 9e1a3c5b7d42
Revises: 8d4f1b7c2e60
"""
from alembic import op
import sqlalchemy as sa

revision = "9e1a3c5b7d42"
down_revision = "8d4f1b7c2e60"
branch_labels = None
depends_on = None

OLD = "HOLIDO — Holistic Development Organization"
NEW = "Kayron Global Tech Services"


def _swap(a, b):
    op.get_bind().execute(sa.text("UPDATE billing_settings SET company_name = :b WHERE company_name = :a"),
                          {"a": a, "b": b})


def upgrade():
    _swap(OLD, NEW)


def downgrade():
    _swap(NEW, OLD)
