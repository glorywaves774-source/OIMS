"""Audit logging helper. Entries are added to the current transaction."""
from flask import g, has_request_context, request
from flask_login import current_user

from app.extensions import db
from app.models import AuditLog


def record(action, summary=None, entity=None, organization_id=None, details=None, actor=None):
    if actor is None and has_request_context() and current_user and current_user.is_authenticated:
        actor = current_user
    if organization_id is None and has_request_context():
        organization_id = g.get("tenant_id")
    entry = AuditLog(
        action=action,
        summary=(summary or "")[:500] or None,
        organization_id=organization_id,
        actor_id=getattr(actor, "id", None),
        actor_email=getattr(actor, "email", None),
        via_support_access=bool(has_request_context() and g.get("support_request")),
        details=details or None,
    )
    if entity is not None:
        entry.entity_type = type(entity).__name__
        entry.entity_id = str(getattr(entity, "id", "") or "")
    if has_request_context():
        entry.ip_address = (request.remote_addr or "")[:64]
        entry.user_agent = (request.user_agent.string or "")[:300]
    db.session.add(entry)
    return entry
