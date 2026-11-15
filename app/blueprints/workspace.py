"""An organization's own workspace. Every route here runs inside a tenant context."""
from datetime import timedelta

from flask import (Blueprint, abort, flash, g, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user, login_required
from sqlalchemy import or_, select

from app import audit
from app.extensions import db
from app.forms import (SCOPE_CHOICES, ActionForm, InviteUserForm, MembershipForm,
                       OrganizationSettingsForm, RoleForm)
from app.models import (AuditLog, Membership, Organization, Role, RolePermission,
                        SupportAccessRequest, User, utcnow)
from app.rbac import (CATALOG, PERMISSION_LABELS, can, permissions_for_role,
                      read_only_permissions, require_permission)
from app.services import ServiceError, active_admin_count, apply_org_fields, invite_user
from app.tenancy import clear_tenant, set_tenant, tenant_get_or_404

bp = Blueprint("workspace", __name__, url_prefix="/o/<org_slug>")


@bp.url_value_preprocessor
def _pull_slug(endpoint, values):
    g.org_slug = values.pop("org_slug", None) if values else None


@bp.url_defaults
def _add_slug(endpoint, values):
    if "org_slug" not in values and g.get("org_slug"):
        values["org_slug"] = g.org_slug


@bp.before_request
@login_required
def _enter_tenant():
    clear_tenant()
    org = Organization.query.filter_by(slug=g.org_slug).first()
    if org is None:
        abort(404)

    # 1. HOLIDO support access: read-only, time-limited, audited.
    req_id = session.get("support_request_id")
    if req_id and current_user.is_platform_staff:
        req = db.session.get(SupportAccessRequest, req_id)
        if req and req.organization_id == org.id and req.requested_by_id == current_user.id:
            if not req.is_live():
                session.pop("support_request_id", None)
                flash("Your support access has expired.", "warning")
                return redirect(url_for("platform.organization_detail", org_id=org.id))
            if request.method not in ("GET", "HEAD"):
                abort(403)
            g.support_request = req
            _activate(org, None, read_only_permissions())
            return None

    # 2. Members of the organization.
    m = Membership.query.filter_by(organization_id=org.id, user_id=current_user.id).first()
    if m is None or m.status != Membership.ACTIVE:
        abort(404)  # do not reveal that the organization exists
    if org.status != Organization.ACTIVE:
        return render_template("workspace/unavailable.html", org=org), 403
    _activate(org, m, permissions_for_role(m.role))
    return None


@bp.after_request
def _audit_support_views(response):
    """Every page HOLIDO support opens inside a tenant workspace is recorded."""
    req = g.get("support_request")
    if req is not None and response.status_code < 400:
        audit.record("support.viewed", f"Viewed {request.path}", entity=req, organization_id=req.organization_id)
        db.session.commit()
    return response


def _activate(org, membership, permissions):
    g.tenant = org
    g.membership = membership
    g.permissions = permissions
    set_tenant(org.id)


def _page():
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


# --- Dashboard ----------------------------------------------------------------------

@bp.route("/")
@require_permission("dashboard.view")
def dashboard():
    org = g.tenant
    status_counts = {}
    for status, in db.session.execute(select(Membership.status).where(Membership.organization_id == org.id)):
        status_counts[status] = status_counts.get(status, 0) + 1
    stats = {
        "members_active": status_counts.get(Membership.ACTIVE, 0),
        "members_invited": status_counts.get(Membership.INVITED, 0),
        "members_suspended": status_counts.get(Membership.SUSPENDED, 0),
        "roles": Role.query.filter_by(organization_id=org.id).count(),
    }
    pending_support = []
    if can("support.view"):
        pending_support = SupportAccessRequest.query.filter_by(
            organization_id=org.id, status=SupportAccessRequest.PENDING).all()
    recent = []
    if can("audit.view"):
        recent = (AuditLog.query.filter_by(organization_id=org.id)
                  .order_by(AuditLog.created_at.desc()).limit(8).all())
    return render_template("workspace/dashboard.html", stats=stats, pending_support=pending_support,
                           recent=recent)


# --- Users ----------------------------------------------------------------------------

def _role_choices():
    return [(r.id, r.name) for r in Role.query.filter_by(organization_id=g.tenant.id).order_by(Role.name)]


@bp.route("/users")
@require_permission("users.view")
def users():
    q = (request.args.get("q") or "").strip()
    stmt = (select(Membership).join(User, Membership.user_id == User.id)
            .where(Membership.organization_id == g.tenant.id).order_by(User.full_name))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.email.ilike(like), Membership.job_title.ilike(like)))
    page = db.paginate(stmt, page=_page(), per_page=25, error_out=False)
    return render_template("workspace/users.html", page=page, q=q, one_time=session.pop("one_time_link", None))


@bp.route("/users/invite", methods=["GET", "POST"])
@require_permission("users.invite")
def user_invite():
    form = InviteUserForm()
    form.role_id.choices = _role_choices()
    if form.validate_on_submit():
        role = db.session.get(Role, form.role_id.data)
        if role and role.is_admin and not can("users.manage"):
            flash("Only users who can manage users may add administrators.", "danger")
        else:
            try:
                m, link = invite_user(g.tenant, form, current_user)
                db.session.commit()
            except ServiceError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
            else:
                if link:
                    session["one_time_link"] = {"email": m.user.email, "link": link}
                flash(f"{m.user.full_name} added.", "success")
                return redirect(url_for("workspace.users"))
    return render_template("workspace/user_invite.html", form=form)


@bp.route("/users/<int:membership_id>", methods=["GET", "POST"])
@require_permission("users.view")
def user_detail(membership_id):
    m = tenant_get_or_404(Membership, membership_id)
    form = MembershipForm(obj=m)
    form.role_id.choices = _role_choices()
    if request.method == "POST":
        if not can("users.manage"):
            abort(403)
        if form.validate_on_submit():
            new_role = tenant_get_or_404(Role, form.role_id.data)
            losing_admin = m.role and m.role.is_admin and not new_role.is_admin and m.status == Membership.ACTIVE
            if losing_admin and active_admin_count(g.tenant.id) <= 1:
                flash("The organization must keep at least one active administrator.", "danger")
            else:
                old = m.role.name if m.role else None
                m.role_id = new_role.id
                m.job_title = form.job_title.data or None
                audit.record("user.updated", f"{m.user.email}: role {old} → {new_role.name}", entity=m)
                db.session.commit()
                flash("Changes saved.", "success")
                return redirect(url_for("workspace.user_detail", membership_id=m.id))
    return render_template("workspace/user_detail.html", m=m, form=form, action_form=ActionForm())


@bp.route("/users/<int:membership_id>/<action>", methods=["POST"])
@require_permission("users.manage")
def user_action(membership_id, action):
    m = tenant_get_or_404(Membership, membership_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    if m.user_id == current_user.id:
        flash("You cannot change your own access here.", "danger")
        return redirect(url_for("workspace.user_detail", membership_id=m.id))
    is_last_admin = (m.role and m.role.is_admin and m.status == Membership.ACTIVE
                     and active_admin_count(g.tenant.id) <= 1)
    if action == "suspend":
        if is_last_admin:
            flash("The organization must keep at least one active administrator.", "danger")
        else:
            m.status = Membership.SUSPENDED
            audit.record("user.suspended", f"{m.user.email} suspended", entity=m)
    elif action == "reactivate":
        m.status = Membership.ACTIVE if m.user.has_password else Membership.INVITED
        audit.record("user.reactivated", f"{m.user.email} reactivated", entity=m)
    elif action == "remove":
        if is_last_admin:
            flash("The organization must keep at least one active administrator.", "danger")
            return redirect(url_for("workspace.user_detail", membership_id=m.id))
        email = m.user.email
        audit.record("user.removed", f"{email} removed from the organization", entity=m)
        db.session.delete(m)
        db.session.commit()
        flash(f"{email} removed.", "success")
        return redirect(url_for("workspace.users"))
    else:
        abort(404)
    db.session.commit()
    return redirect(url_for("workspace.user_detail", membership_id=m.id))


# --- Roles -----------------------------------------------------------------------------

@bp.route("/roles")
@require_permission("roles.view")
def roles():
    rows = Role.query.filter_by(organization_id=g.tenant.id).order_by(Role.is_system.desc(), Role.name).all()
    counts = {}
    for (rid,) in db.session.execute(select(Membership.role_id).where(Membership.organization_id == g.tenant.id)):
        counts[rid] = counts.get(rid, 0) + 1
    return render_template("workspace/roles.html", roles=rows, counts=counts, action_form=ActionForm())


def _save_permissions(role):
    role.permissions.clear()
    db.session.flush()
    for code in request.form.getlist("perm"):
        if code in PERMISSION_LABELS:
            scope = request.form.get(f"scope__{code}", RolePermission.SCOPE_ORGANIZATION)
            if scope not in RolePermission.SCOPES:
                scope = RolePermission.SCOPE_ORGANIZATION
            role.permissions.append(RolePermission(permission_code=code, scope=scope))


@bp.route("/roles/new", methods=["GET", "POST"])
@bp.route("/roles/<int:role_id>", methods=["GET", "POST"])
@require_permission("roles.view")
def role_edit(role_id=None):
    role = tenant_get_or_404(Role, role_id) if role_id else None
    source = None
    if role is None and request.args.get("from"):
        source = tenant_get_or_404(Role, request.args.get("from", type=int))
    form = RoleForm(obj=role)
    if role is None and source is not None and request.method == "GET":
        form.name.data = f"{source.name} (custom)"
        form.description.data = source.description
    editable = can("roles.manage") and (role is None or not role.is_system)
    if request.method == "POST":
        if not editable:
            abort(403)
        if form.validate_on_submit():
            clash = Role.query.filter(Role.organization_id == g.tenant.id, Role.name == form.name.data,
                                      Role.id != (role.id if role else 0)).first()
            if clash:
                form.name.errors.append("Another role already has this name.")
            else:
                creating = role is None
                if creating:
                    role = Role(organization_id=g.tenant.id)
                    db.session.add(role)
                role.name = form.name.data
                role.description = form.description.data or None
                _save_permissions(role)
                db.session.flush()
                audit.record("role.created" if creating else "role.updated", f"Role {role.name} saved",
                             entity=role, details={"permissions": sorted(role.permission_map())})
                db.session.commit()
                flash("Role saved.", "success")
                return redirect(url_for("workspace.roles"))
    if role is not None:
        current = role.permission_map() if not role.is_admin else {c: "organization" for c in PERMISSION_LABELS}
    elif source is not None:
        current = source.permission_map() if not source.is_admin else {c: "organization" for c in PERMISSION_LABELS}
    else:
        current = {}
    if request.method == "POST":
        current = {c: request.form.get(f"scope__{c}", "organization") for c in request.form.getlist("perm")}
    return render_template("workspace/role_edit.html", role=role, form=form, catalog=CATALOG,
                           current=current, scopes=SCOPE_CHOICES, editable=editable)


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@require_permission("roles.manage")
def role_delete(role_id):
    role = tenant_get_or_404(Role, role_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    if role.is_system:
        flash("System roles cannot be deleted.", "danger")
    elif Membership.query.filter_by(organization_id=g.tenant.id, role_id=role.id).count():
        flash("Move the people in this role to another role first.", "danger")
    else:
        audit.record("role.deleted", f"Role {role.name} deleted", entity=role)
        db.session.delete(role)
        db.session.commit()
        flash("Role deleted.", "success")
    return redirect(url_for("workspace.roles"))


# --- Settings ----------------------------------------------------------------------------

@bp.route("/settings", methods=["GET", "POST"])
@require_permission("organization.view")
def settings():
    org = g.tenant
    form = OrganizationSettingsForm(obj=org)
    if request.method == "POST":
        if not can("organization.manage"):
            abort(403)
        if form.validate_on_submit():
            try:
                apply_org_fields(org, form)
            except ServiceError as exc:
                form.logo.errors.append(str(exc))
            else:
                if form.remove_logo.data:
                    org.logo_data = org.logo_mime = None
                org.currency = form.currency.data
                org.fiscal_year_start_month = form.fiscal_year_start_month.data
                org.timezone = form.timezone.data
                org.require_support_approval = form.require_support_approval.data
                audit.record("organization.settings_updated", "Organization profile and settings updated", entity=org)
                db.session.commit()
                flash("Settings saved.", "success")
                return redirect(url_for("workspace.settings"))
    return render_template("workspace/settings.html", form=form, org=org, editable=can("organization.manage"))


# --- Audit ---------------------------------------------------------------------------------

@bp.route("/audit")
@require_permission("audit.view")
def audit_log():
    action = (request.args.get("action") or "").strip()
    stmt = select(AuditLog).where(AuditLog.organization_id == g.tenant.id).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    page = db.paginate(stmt, page=_page(), per_page=40, error_out=False)
    return render_template("workspace/audit.html", page=page, action=action)


# --- HOLIDO support access ------------------------------------------------------------------

@bp.route("/support")
@require_permission("support.view")
def support():
    rows = (SupportAccessRequest.query.filter_by(organization_id=g.tenant.id)
            .order_by(SupportAccessRequest.created_at.desc()).limit(50).all())
    return render_template("workspace/support.html", rows=rows, action_form=ActionForm())


@bp.route("/support/<int:req_id>/<action>", methods=["POST"])
@require_permission("support.approve")
def support_decide(req_id, action):
    req = tenant_get_or_404(SupportAccessRequest, req_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    now = utcnow()
    if action == "approve" and req.status == SupportAccessRequest.PENDING:
        req.status = SupportAccessRequest.APPROVED
        req.starts_at = now
        req.expires_at = now + timedelta(minutes=req.duration_minutes)
    elif action == "deny" and req.status == SupportAccessRequest.PENDING:
        req.status = SupportAccessRequest.DENIED
    elif action == "revoke" and req.is_live():
        req.status = SupportAccessRequest.REVOKED
        req.expires_at = now
    else:
        flash("This request can no longer be changed.", "warning")
        return redirect(url_for("workspace.support"))
    req.decided_by_id = current_user.id
    req.decided_at = now
    audit.record(f"support.{action}", f"Support access {req.status} for {req.requested_by.email}", entity=req)
    db.session.commit()
    flash(f"Support access {req.status}.", "success")
    return redirect(url_for("workspace.support"))
