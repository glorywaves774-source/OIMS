from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import declared_attr

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)


class TenantMixin:
    """Every tenant-owned table inherits this.

    The tenancy guard (app/tenancy.py) automatically restricts every SELECT on
    these models to the organization of the current request, stamps new rows
    with that organization, and refuses to move rows between organizations.
    """

    @declared_attr
    def organization_id(cls):
        return db.Column(
            db.Integer,
            db.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


def as_aware(dt):
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


__all__ = ["db", "sa", "utcnow", "TimestampMixin", "TenantMixin", "as_aware"]
