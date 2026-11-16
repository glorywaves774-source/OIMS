"""Shared plumbing for every organization-workspace blueprint (/o/<org_slug>/...).

Each module blueprint is created with ``workspace_blueprint()`` so that all of them
verify membership (or live support access), set the tenant context and permissions,
refuse writes during support access, and log support page views — identically.
"""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import false, or_, select

from app import audit
from app.extensions import db
from app.models import Membership, Organization, StaffProfile, SupportAccessRequest, User
from app.rbac import DEPT, ORG, OWN, READ_ONLY_ACTIONS, permissions_for_role, read_only_permissions, scope_of
from app.tenancy import clear_tenant, set_tenant


def workspace_blueprint(name, import_name, prefix=""):
    bp = Blueprint(name, import_name, url_prefix="/o/<org_slug>" + prefix)
    bp.url_value_preprocessor(_pull_slug)
    bp.url_defaults(_add_slug)
    bp.before_request(_enter_tenant)
    bp.after_request(_audit_support_views)
    return bp


def _pull_slug(endpoint, values):
    g.org_slug = values.pop("org_slug", None) if values else None


def _add_slug(endpoint, values):
    if "org_slug" not in values and g.get("org_slug"):
        values["org_slug"] = g.org_slug


@login_required
def _enter_tenant():
    clear_tenant()
    org = Organization.query.filter_by(slug=g.org_slug).first()
    if org is None:
        abort(404)

    # 1. Kayron support access: read-only, time-limited, audited.
    req_id = session.get("support_request_id")
    if req_id and current_user.is_platform_staff:
        req = db.session.get(SupportAccessRequest, req_id)
        if req and req.organization_id == org.id and req.requested_by_id == current_user.id:
            if not req.is_live():
                session.pop("support_request_id", None)
                flash("Your support access has expired.", "warning")
                return redirect(url_for("platform.organization_detail", org_id=org.id))
            if request.method not in ("GET", "HEAD") and request.blueprint != "assistant":
                abort(403)   # read-only; asking the help assistant changes nothing
            g.support_request = req
            _activate(org, None, read_only_permissions())
            return None

    # 2. Members of the organization.
    m = Membership.query.filter_by(organization_id=org.id, user_id=current_user.id).first()
    if m is None or m.status != Membership.ACTIVE:
        abort(404)  # do not reveal that the organization exists
    if org.status != Organization.ACTIVE:
        return render_template("workspace/unavailable.html", org=org), 403
    perms = permissions_for_role(m.role)
    from app.billing import state as billing_state
    set_tenant(org.id)
    st = billing_state(org)
    g.billing = st
    if st["locked"]:
        # Lapsed or cancelled subscription: everyone can still read and export; only billing stays open.
        perms = {c: sc for c, sc in perms.items() if c.split(".")[1] in READ_ONLY_ACTIONS or c.startswith("billing.")}
        if request.method not in ("GET", "HEAD") and request.blueprint not in ("billing", "assistant"):
            g.tenant = org
            return render_template("workspace/billing_locked.html", org=org, st=st), 403
    _activate(org, m, perms)
    return None


def _activate(org, membership, permissions):
    g.tenant = org
    g.membership = membership
    g.permissions = permissions
    set_tenant(org.id)


def _audit_support_views(response):
    """Every page Kayron support opens inside a tenant workspace is recorded."""
    req = g.get("support_request")
    if req is not None and response.status_code < 400:
        audit.record("support.viewed", f"Viewed {request.path}", entity=req, organization_id=req.organization_id)
        db.session.commit()
    return response


# --- Helpers for module views ---------------------------------------------------------

def page_arg():
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


def my_staff():
    """The current user's staff profile in this organization (or None)."""
    if "my_staff" not in g:
        g.my_staff = None
        if current_user.is_authenticated and g.get("tenant") is not None:
            g.my_staff = StaffProfile.query.filter(
                StaffProfile.organization_id == g.tenant.id, StaffProfile.user_id == current_user.id,
                StaffProfile.status != "exited").first()
    return g.my_staff


def my_department_id():
    s = my_staff()
    return s.department_id if s else None


def scoped(stmt, code, dept_col=None, own_cols=()):
    """Restrict a statement to what the person's scope for ``code`` allows."""
    scope = scope_of(code)
    if scope == ORG:
        return stmt
    conditions = []
    if scope in (DEPT,) and dept_col is not None and my_department_id() is not None:
        conditions.append(dept_col == my_department_id())
    if scope in (DEPT, OWN):
        conditions.extend(col == current_user.id for col in own_cols)
    if not conditions:
        return stmt.where(false())
    return stmt.where(or_(*conditions))


def in_scope(code, department_id=None, owner_ids=()):
    """Check one record against the person's scope for ``code``."""
    scope = scope_of(code)
    if scope == ORG:
        return True
    if scope is None:
        return False
    if current_user.id in owner_ids:
        return True
    return scope == DEPT and department_id is not None and department_id == my_department_id()


def member_users(active_only=True):
    """Users with a membership in the current organization, sorted by name."""
    stmt = (select(User).join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == g.tenant.id))
    if active_only:
        stmt = stmt.where(Membership.status == Membership.ACTIVE)
    return db.session.execute(stmt.order_by(User.full_name)).scalars().all()


def member_choices(blank=None):
    choices = [(u.id, u.full_name) for u in member_users()]
    return ([(0, blank)] if blank else []) + choices


def is_member(user_id):
    return Membership.query.filter_by(organization_id=g.tenant.id, user_id=user_id,
                                      status=Membership.ACTIVE).first() is not None
