"""Converting between the organization's local time and stored UTC."""
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import g


def org_zone():
    tenant = g.get("tenant")
    try:
        return ZoneInfo(tenant.timezone if tenant else "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_utc(naive_local):
    """Organization-local naive datetime (from a form) -> aware UTC."""
    if naive_local is None:
        return None
    return naive_local.replace(tzinfo=org_zone()).astimezone(timezone.utc)


def to_local(dt):
    """Stored datetime -> organization-local aware datetime (for display and forms)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(org_zone())


def local_naive(dt):
    loc = to_local(dt)
    return loc.replace(tzinfo=None) if loc else None
