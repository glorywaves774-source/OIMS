"""Permission catalog, default organizational role templates and checks.

Permissions are ``module.action`` codes, each granted with a scope:
``organization`` (everything in the organization), ``department`` (records of the
person's own department) or ``own`` (records the person created or is assigned to).

Each phase adds its modules to CATALOG; ``flask oims sync-roles`` grants newly added
permissions to existing standard roles according to their templates.
"""
from fnmatch import fnmatch
from functools import wraps

from flask import abort, g

from app.models import Role, RolePermission

ORG, DEPT, OWN = "organization", "department", "own"
SCOPE_WIDTH = {OWN: 1, DEPT: 2, ORG: 3}

# module -> (label, [(action, label), ...])
CATALOG = {
    "dashboard": ("Dashboard", [("view", "View the workspace dashboard")]),
    "organization": ("Organization profile & settings", [
        ("view", "View organization profile"),
        ("manage", "Edit profile, logo, workspace settings and office lists"),
    ]),
    "users": ("Users & memberships", [
        ("view", "View users"),
        ("invite", "Invite users"),
        ("manage", "Change roles, suspend and remove users"),
    ]),
    "roles": ("Roles & permissions", [("view", "View roles"), ("manage", "Create and edit custom roles")]),
    "audit": ("Audit log", [("view", "View the organization audit log")]),
    "support": ("Kayron support access", [
        ("view", "View support access requests"),
        ("approve", "Approve, deny or revoke support access"),
    ]),
    "departments": ("Departments", [("view", "View departments"), ("manage", "Create and edit departments")]),
    "staff": ("Staff & HR", [
        ("view", "View the staff directory"),
        ("records", "View HR records (contracts, leave, attendance, training, performance, exit)"),
        ("manage", "Register staff and maintain HR records"),
    ]),
    "leave": ("Leave", [
        ("request", "Request leave for myself"),
        ("approve", "Approve or reject leave requests"),
        ("manage", "Configure leave types"),
    ]),
    "attendance": ("Attendance", [("record", "Record attendance")]),
    "documents": ("Documents & records", [
        ("view", "View documents shared with me"),
        ("upload", "Upload documents and new versions of my documents"),
        ("approve", "Approve or reject documents"),
        ("manage", "Manage all documents, folders and categories"),
    ]),
    "correspondence": ("Correspondence", [
        ("view", "View correspondence"),
        ("create", "Register letters and memos"),
        ("approve", "Approve correspondence"),
        ("manage", "Assign, forward, close and archive any correspondence"),
    ]),
    "meetings": ("Meetings", [
        ("view", "View meetings"),
        ("create", "Schedule meetings"),
        ("manage", "Edit any meeting and record minutes"),
    ]),
    "tasks": ("Tasks", [
        ("view", "View tasks"),
        ("create", "Create and assign tasks"),
        ("manage", "Edit, reassign and close any task"),
    ]),
    "calendar": ("Calendar", [("view", "View calendars")]),
    "announcements": ("Announcements", [("view", "Read announcements"), ("manage", "Publish announcements")]),
    "messages": ("Internal messages", [("use", "Send and receive internal messages")]),
    "programmes": ("Programmes", [
        ("view", "View programmes"),
        ("create", "Register new programmes"),
        ("edit", "Plan and implement programmes (framework, workplans, activities, milestones)"),
        ("manage", "Change programme status, manager and team; approve workplans; delete"),
    ]),
    "projects": ("Projects", [
        ("view", "View projects"),
        ("create", "Register new projects"),
        ("edit", "Plan and implement projects (work breakdown, activities, deliverables, risks)"),
        ("manage", "Change project status, manager and team; approve workplans, verify deliverables, approve closure"),
    ]),
    "finance": ("Programme & project finance", [
        ("view", "View budgets, funding and expenditure"),
        ("record", "Prepare budgets and record expenditure, commitments and funding received"),
        ("approve", "Approve expenditure and budget revisions"),
        ("manage", "Manage donors and budget categories"),
        ("rates", "Set exchange rates used to combine currencies"),
    ]),
    "meal": ("Monitoring, evaluation, accountability & learning", [
        ("view", "View indicators, results, visits and evaluations"),
        ("collect", "Report indicator results, activity reports and monitoring visits"),
        ("edit", "Define indicators and targets, verify results, record evaluations and learning"),
    ]),
    "billing": ("Subscription & billing", [
        ("view", "See the plan, usage and invoices"),
        ("manage", "Pay invoices, change the plan or cancel the subscription"),
    ]),
    "procurement": ("Procurement", [
        ("view", "View purchase requests, quotations, orders and suppliers"),
        ("request", "Raise purchase requests"),
        ("approve", "Approve or reject purchase requests"),
        ("manage", "Handle quotations, purchase orders, goods received, suppliers and thresholds"),
    ]),
    "assets": ("Assets", [
        ("view", "View the asset register"),
        ("manage", "Register, assign, transfer, maintain and verify assets; request disposal"),
        ("approve", "Approve asset disposals"),
    ]),
    "beneficiaries": ("Beneficiaries", [
        ("view", "View the beneficiary register (name, sex, age group, place, enrolment)"),
        ("register", "Register beneficiaries; record consent, enrolment, services and attendance"),
        ("sensitive", "See and edit personal details: phone, ID number, date of birth, vulnerability, notes"),
        ("manage", "Correct any record, merge duplicates, exit and anonymize people"),
        ("export", "Export beneficiary lists"),
    ]),
    "feedback": ("Feedback & complaints", [
        ("view", "View feedback and complaints"),
        ("record", "Record feedback received from communities"),
        ("manage", "Assign, respond to and close feedback; publish the public feedback page"),
        ("sensitive", "Handle sensitive cases (safeguarding, fraud, misconduct)"),
    ]),
    "reports": ("Programme reports", [
        ("view", "View reports and export them"),
        ("create", "Write and submit reports"),
        ("approve", "Approve reports"),
    ]),
}

ALL_PERMISSIONS = [f"{m}.{a}" for m, (_, actions) in CATALOG.items() for a, _ in actions]
PERMISSION_LABELS = {f"{m}.{a}": lbl for m, (_, actions) in CATALOG.items() for a, lbl in actions}
READ_ONLY_ACTIONS = {"view"}

ADMIN_ROLE_NAME = "Organization Administrator"

# Everyone with a standard role gets the basic office tools.
BASE = ["dashboard.view", "organization.view", "departments.view", "staff.view", "leave.request",
        "documents.view", "documents.upload", "meetings.view@own", "tasks.view@own", "tasks.create",
        "calendar.view", "announcements.view", "messages.use", "assets.view@own"]

# "pattern@scope" — later entries override earlier ones. Patterns for modules that do not
# exist yet (e.g. "programmes.*") take effect when those modules are added.
ROLE_TEMPLATES = [
    (ADMIN_ROLE_NAME, "Full control of the organization workspace.", None),
    ("Executive Director", "Organization-wide oversight and approvals.",
     BASE + ["*.view", "support.approve", "documents.approve", "correspondence.*", "leave.approve",
             "meetings.*", "tasks.*", "announcements.manage", "programmes.*", "projects.*",
             "finance.approve", "reports.*", "meal.view", "procurement.approve", "assets.approve"]),
    ("Programme Director", "Leads programmes and their projects.",
     BASE + ["users.view", "meetings.*", "tasks.*", "programmes.*", "projects.*", "meal.*", "reports.*",
             "finance.view", "finance.record", "beneficiaries.view", "beneficiaries.register",
             "beneficiaries.export", "feedback.view", "feedback.record", "feedback.manage",
             "procurement.view", "procurement.request", "procurement.approve", "assets.view"]),
    ("Project Manager", "Manages assigned projects.",
     BASE + ["users.view", "meetings.create", "meetings.view", "tasks.*", "projects.view", "projects.create",
             "projects.edit@own", "projects.manage@own", "reports.view@own", "reports.create@own",
             "programmes.view@own", "finance.view@own", "finance.record@own", "meal.view@own", "meal.collect@own",
             "beneficiaries.view@own", "beneficiaries.register@own", "beneficiaries.sensitive@own",
             "feedback.view@own", "feedback.record", "feedback.manage@own",
             "procurement.view@own", "procurement.request@own", "procurement.approve@own", "assets.view@own"]),
    ("Programme Officer", "Supports programme implementation.",
     BASE + ["programmes.view", "programmes.edit@own", "projects.view", "meetings.create", "meal.view",
             "meal.collect@own", "reports.view", "reports.create@own", "finance.view@own",
             "beneficiaries.view", "beneficiaries.register@own", "feedback.view@own", "feedback.record",
             "procurement.view@own", "procurement.request@own"]),
    ("Project Officer", "Supports project implementation.",
     BASE + ["projects.view", "projects.edit@own", "meetings.create", "programmes.view@own", "meal.view@own",
             "meal.collect@own", "reports.view@own", "finance.view@own",
             "beneficiaries.view@own", "beneficiaries.register@own", "feedback.view@own", "feedback.record",
             "procurement.view@own", "procurement.request@own"]),
    ("MEAL Officer", "Monitoring, evaluation, accountability and learning.",
     BASE + ["meal.*", "beneficiaries.*", "programmes.view", "projects.view", "reports.*",
             "feedback.view", "feedback.record", "feedback.manage"]),
    ("Finance Officer", "Budgets, expenditure and financial reporting.",
     BASE + ["finance.*", "programmes.view", "projects.view", "reports.view", "procurement.view", "assets.view",
             "billing.view"]),
    ("Logistics & Assets Officer", "Keeps the asset register: tags, assignments, maintenance and checks.",
     BASE + ["assets.view", "assets.manage", "procurement.view", "programmes.view", "projects.view"]),
    ("HR Officer", "Staff administration.",
     BASE + ["users.view", "staff.*", "leave.*", "attendance.record", "departments.*", "announcements.manage"]),
    ("Procurement Officer", "Procurement and suppliers.",
     BASE + ["procurement.view", "procurement.request", "procurement.manage", "assets.view", "assets.manage",
             "programmes.view", "projects.view", "finance.view"]),
    ("Records Officer", "Documents, records and correspondence.",
     BASE + ["documents.*", "correspondence.*"]),
    ("Department Head", "Leads a department.",
     BASE + ["users.view", "staff.records@department", "leave.approve@department", "attendance.record@department",
             "tasks.*@department", "tasks.create", "meetings.create", "meetings.view@department",
             "correspondence.view@department", "documents.approve", "programmes.view@department",
             "projects.view@department",
             "meal.view@department", "finance.view@department", "reports.view@department",
             "beneficiaries.view@department", "feedback.view@department", "procurement.view@department",
             "procurement.request@department", "assets.view@department"]),
    ("Field Officer", "Field implementation and data collection.",
     BASE + ["meal.collect@own", "programmes.view@own", "projects.view@own", "meal.view@own",
             "beneficiaries.view@own", "beneficiaries.register@own", "beneficiaries.sensitive@own",
             "feedback.view@own", "feedback.record"]),
    ("Safeguarding Focal Point", "Receives and handles sensitive complaints confidentially.",
     BASE + ["feedback.*", "beneficiaries.view", "beneficiaries.sensitive", "programmes.view", "projects.view"]),
    ("Staff Member", "Standard staff access.", BASE),
    ("Read-only / Auditor", "Read-only access to all records, including the audit log.",
     ["*.view"]),
]


def expand_template(patterns):
    """Return {code: scope} for a template's patterns (later patterns override earlier ones)."""
    result = {}
    for entry in patterns:
        pattern, _, scope = entry.partition("@")
        scope = scope or ORG
        for code in ALL_PERMISSIONS:
            if fnmatch(code, pattern):
                result[code] = scope
    return result


def expand_patterns(patterns):  # kept for backwards compatibility
    return list(expand_template(patterns))


def seed_default_roles(organization):
    """Create/refresh the standard roles of an organization. Returns the admin role."""
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
            continue
        wanted = expand_template(patterns)
        have = {p.permission_code: p for p in role.permissions}
        for code, scope in wanted.items():
            if code in have:
                have[code].scope = scope
            else:
                role.permissions.append(RolePermission(permission_code=code, scope=scope))
        for code, rp in have.items():  # standard roles always match their template exactly
            if code not in wanted:
                role.permissions.remove(rp)
    db.session.flush()
    return admin_role


# --- Request-time checks ---------------------------------------------------

def effective_permissions():
    """{code: scope} for the current workspace request (set by the workspace blueprint)."""
    return g.get("permissions") or {}


def can(code):
    return code in effective_permissions()


def scope_of(code):
    return effective_permissions().get(code)


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
        return {}
    if role.is_admin:
        return {c: ORG for c in ALL_PERMISSIONS}
    return {c: s for c, s in role.permission_map().items() if c in PERMISSION_LABELS}


def read_only_permissions():
    return {c: ORG for c in ALL_PERMISSIONS if c.split(".")[1] in READ_ONLY_ACTIONS}
