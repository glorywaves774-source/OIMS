"""Permission catalog, default organizational role templates and checks.

Permissions are ``module.action`` codes. Each phase adds its modules to CATALOG;
``flask oims sync-roles`` grants newly added permissions to existing system roles
according to their templates.
"""
from fnmatch import fnmatch
from functools import wraps

from flask import abort, g

from app.models import Role, RolePermission

# module -> (label, [(action, label), ...])
CATALOG = {
    "dashboard": ("Dashboard", [("view", "View the workspace dashboard")]),
    "organization": ("Organization profile & settings", [
        ("view", "View organization profile"),
        ("manage", "Edit profile, logo and workspace settings"),
    ]),
    "users": ("Users & memberships", [
        ("view", "View users"),
        ("invite", "Invite users"),
        ("manage", "Change roles, suspend and remove users"),
    ]),
    "roles": ("Roles & permissions", [
        ("view", "View roles"),
        ("manage", "Create and edit custom roles"),
    ]),
    "audit": ("Audit log", [("view", "View the organization audit log")]),
    "support": ("HOLIDO support access", [
        ("view", "View support access requests"),
        ("approve", "Approve, deny or revoke support access"),
    ]),
}

ALL_PERMISSIONS = [f"{m}.{a}" for m, (_, actions) in CATALOG.items() for a, _ in actions]
PERMISSION_LABELS = {f"{m}.{a}": lbl for m, (_, actions) in CATALOG.items() for a, lbl in actions}
READ_ONLY_ACTIONS = {"view"}

ADMIN_ROLE_NAME = "Organization Administrator"

# Role templates from the specification. Patterns are matched against the catalog,
# so permissions added in later phases (e.g. "programmes.*") apply automatically.
ROLE_TEMPLATES = [
    (ADMIN_ROLE_NAME, "Full control of the organization workspace.", None),
    ("Executive Director", "Organization-wide oversight and approvals.",
     ["*.view", "support.approve", "programmes.*", "projects.*", "finance.approve", "reports.*"]),
    ("Programme Director", "Leads programmes and their projects.",
     ["dashboard.view", "organization.view", "users.view", "programmes.*", "projects.*", "meal.*", "reports.*"]),
    ("Project Manager", "Manages assigned projects.",
     ["dashboard.view", "organization.view", "users.view", "projects.*", "tasks.*", "reports.view"]),
    ("Programme Officer", "Supports programme implementation.",
     ["dashboard.view", "organization.view", "programmes.view", "programmes.edit", "projects.view", "tasks.*"]),
    ("Project Officer", "Supports project implementation.",
     ["dashboard.view", "organization.view", "projects.view", "projects.edit", "tasks.*"]),
    ("MEAL Officer", "Monitoring, evaluation, accountability and learning.",
     ["dashboard.view", "organization.view", "meal.*", "beneficiaries.*", "programmes.view", "projects.view", "reports.*"]),
    ("Finance Officer", "Budgets, expenditure and financial reporting.",
     ["dashboard.view", "organization.view", "finance.*", "programmes.view", "projects.view", "reports.*"]),
    ("HR Officer", "Staff administration.",
     ["dashboard.view", "organization.view", "users.view", "staff.*", "departments.view"]),
    ("Procurement Officer", "Procurement and suppliers.",
     ["dashboard.view", "organization.view", "procurement.*", "assets.view"]),
    ("Records Officer", "Documents, records and correspondence.",
     ["dashboard.view", "organization.view", "documents.*", "correspondence.*"]),
    ("Department Head", "Leads a department.",
     ["dashboard.view", "organization.view", "users.view", "departments.view", "staff.view", "tasks.*"]),
    ("Field Officer", "Field implementation and data collection.",
     ["dashboard.view", "organization.view", "tasks.view", "tasks.edit", "meal.collect"]),
    ("Staff Member", "Standard staff access.",
     ["dashboard.view", "organization.view", "tasks.view"]),
    ("Read-only / Auditor", "Read-only access to all records, including the audit log.",
     ["*.view"]),
]


def expand_patterns(patterns):
    return [code for code in ALL_PERMISSIONS if any(fnmatch(code, p) for p in patterns)]


def seed_default_roles(organization):
    """Create the system roles for a newly approved organization. Returns the admin role."""
    from app.extensions import db

    existing = {r.name: r for r in Role.query.filter_by(organization_id=organization.id).all()}
    admin_role = None
    for name, description, patterns in ROLE_TEMPLATES:
        role = existing.get(name)
        if role is None:
            role = Role(organization_id=organization.id, name=name, description=description, is_system=True)
            db.session.add(role)
        if patterns is None:
            role.is_admin = True
            admin_role = role
        else:
            have = {p.permission_code for p in role.permissions}
            for code in expand_patterns(patterns):
                if code not in have:
                    role.permissions.append(RolePermission(permission_code=code))
    db.session.flush()
    return admin_role


# --- Request-time checks ---------------------------------------------------

def effective_permissions():
    """Set of permission codes for the current workspace request (set by the org blueprint)."""
    return g.get("permissions", frozenset())


def can(code):
    return code in effective_permissions()


def require_permission(*codes):
    """Route decorator: the current workspace user must hold every listed permission."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            perms = effective_permissions()
            if not all(c in perms for c in codes):
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def permissions_for_role(role):
    if role is None:
        return frozenset()
    if role.is_admin:
        return frozenset(ALL_PERMISSIONS)
    return frozenset(c for c in role.permission_map() if c in PERMISSION_LABELS)


def read_only_permissions():
    return frozenset(c for c in ALL_PERMISSIONS if c.split(".")[1] in READ_ONLY_ACTIONS)
