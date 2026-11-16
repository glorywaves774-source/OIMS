"""Each person's language (English or French).

Revision ID: b5d1f3a7c9e2
Revises: a3c7e9f1b2d4
"""
from alembic import op
import sqlalchemy as sa

revision = "b5d1f3a7c9e2"
down_revision = "a3c7e9f1b2d4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("language", sa.String(5)))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("language")
