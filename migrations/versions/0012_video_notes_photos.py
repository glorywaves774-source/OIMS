"""Video calls and live notes for meetings; staff profile photos.

Revision ID: d4f6a8b0c2e5
Revises: c8e2a4f6b1d3
"""
from alembic import op
import sqlalchemy as sa

revision = "d4f6a8b0c2e5"
down_revision = "c8e2a4f6b1d3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("meetings") as batch:
        batch.add_column(sa.Column("video_room", sa.String(80)))
        batch.add_column(sa.Column("transcript", sa.Text()))
        batch.add_column(sa.Column("transcript_updated_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("staff_profiles") as batch:
        batch.add_column(sa.Column("photo_data", sa.LargeBinary()))
        batch.add_column(sa.Column("photo_updated_at", sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table("staff_profiles") as batch:
        batch.drop_column("photo_updated_at")
        batch.drop_column("photo_data")
    with op.batch_alter_table("meetings") as batch:
        batch.drop_column("transcript_updated_at")
        batch.drop_column("transcript")
        batch.drop_column("video_room")
