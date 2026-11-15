"""Tenant isolation guard.

Defence in depth:
1. Every ORM SELECT touching a TenantMixin model is automatically restricted to the
   current organization (``with_loader_criteria``), including relationship loads.
2. New tenant rows are stamped with the current organization; rows assigned to a
   different organization, or moved between organizations, abort the flush.
3. Route helpers (``tenant_get_or_404``) filter explicitly as well.

Tenant context is set per request by the organization workspace blueprint after it
has verified an active membership or a live, approved support-access grant.
Platform (HOLIDO) pages run without a tenant context and are protected by
platform-role checks instead.
"""
from flask import abort, g, has_app_context
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session, with_loader_criteria

from app.extensions import db
from app.models import TenantMixin


class TenantIsolationError(RuntimeError):
    pass


def current_tenant_id():
    if not has_app_context():
        return None
    return g.get("tenant_id")


def set_tenant(organization_id):
    g.tenant_id = organization_id


def clear_tenant():
    g.pop("tenant_id", None)


@event.listens_for(Session, "do_orm_execute")
def _restrict_to_tenant(execute_state):
    if not execute_state.is_select:
        return
    if execute_state.execution_options.get("skip_tenant_filter"):
        return
    tenant_id = current_tenant_id()
    if tenant_id is None:
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(
            TenantMixin,
            lambda cls: cls.organization_id == tenant_id,
            include_aliases=True,
        )
    )


@event.listens_for(Session, "before_flush")
def _stamp_and_check_tenant(session, flush_context, instances):
    tenant_id = current_tenant_id()
    for obj in session.new:
        if not isinstance(obj, TenantMixin):
            continue
        if obj.organization_id is None:
            if tenant_id is None:
                raise TenantIsolationError(f"{type(obj).__name__} created without an organization")
            obj.organization_id = tenant_id
        elif tenant_id is not None and obj.organization_id != tenant_id:
            raise TenantIsolationError("Attempt to create a record in another organization")
    for obj in session.dirty:
        if not isinstance(obj, TenantMixin):
            continue
        hist = inspect(obj).attrs.organization_id.history
        if hist.has_changes() and hist.deleted and hist.deleted[0] is not None:
            raise TenantIsolationError("Records cannot be moved between organizations")
        if tenant_id is not None and obj.organization_id != tenant_id:
            raise TenantIsolationError("Attempt to modify a record in another organization")
    for obj in session.deleted:
        if isinstance(obj, TenantMixin) and tenant_id is not None and obj.organization_id != tenant_id:
            raise TenantIsolationError("Attempt to delete a record in another organization")


def tenant_get_or_404(model, ident):
    """Fetch a tenant-owned record by id, constrained to the current organization."""
    tenant_id = current_tenant_id()
    if tenant_id is None or not issubclass(model, TenantMixin):
        abort(404)
    obj = db.session.execute(
        select(model).where(model.id == ident, model.organization_id == tenant_id)
    ).scalar_one_or_none()
    if obj is None:
        abort(404)
    return obj


def unscoped(stmt):
    """Mark a statement as intentionally cross-tenant (e.g. listing a user's own memberships)."""
    return stmt.execution_options(skip_tenant_filter=True)
