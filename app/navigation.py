"""Sidebar groups and phone tab bar, built per request from the person's access."""
from flask import g, request, url_for
from flask_login import current_user

from app.models import PlatformRole
from app.rbac import can


def _item(label, icon, endpoint, short=None, match=None, **values):
    current = request.endpoint or ""
    active = current == endpoint or (match is not None and current.startswith(match))
    return {"label": label, "icon": icon, "url": url_for(endpoint, **values), "endpoint": endpoint,
            "short": short or label, "active": active}


def header_counts():
    """Unread notifications and messages for the top bar (workspace pages only)."""
    if not current_user.is_authenticated or g.get("tenant") is None or g.get("support_request") is not None:
        return {}
    if "header_counts" not in g:
        from app.blueprints.comms import unread_messages_count
        from app.notify import unread_count
        g.header_counts = {"notifications": unread_count(current_user.id, g.tenant.id),
                           "messages": unread_messages_count() if can("messages.use") else 0}
    return g.header_counts


def build_nav():
    if not current_user.is_authenticated:
        return {"groups": [], "tabs": []}
    groups = []
    tabs = []
    if g.get("tenant") is not None:
        home = [_item("Dashboard", "bi-grid-1x2", "workspace.dashboard", "Home")] if can("dashboard.view") else []
        if can("calendar.view"):
            home.append(_item("Calendar", "bi-calendar3", "comms.calendar", "Calendar"))
        home.append(_item("Notifications", "bi-bell", "comms.notifications", "Alerts"))
        if can("messages.use"):
            home.append(_item("Messages", "bi-chat-dots", "comms.inbox", "Messages", match="comms.conversation"))
        office = []
        if can("tasks.view") or can("tasks.create"):
            office.append(_item("Tasks", "bi-check2-square", "tasks.index", "Tasks", match="tasks."))
        if can("meetings.view"):
            office.append(_item("Meetings", "bi-people-fill", "meetings.index", "Meetings", match="meetings."))
        if can("documents.view"):
            office.append(_item("Documents", "bi-folder2-open", "documents.index", "Docs", match="documents."))
        if can("correspondence.view") or can("correspondence.create"):
            office.append(_item("Correspondence", "bi-envelope-paper", "correspondence.index", "Letters",
                                match="correspondence."))
        if can("announcements.view"):
            office.append(_item("Announcements", "bi-megaphone", "comms.announcements", "News", match="comms.announcement"))
        progs = []
        if can("programmes.view"):
            progs.append(_item("Programmes", "bi-kanban", "programmes.index", "Programmes", match="programmes."))
        if can("projects.view"):
            progs.append(_item("Projects", "bi-briefcase", "projects.index", "Projects", match="projects."))
        if can("programmes.view") or can("projects.view") or can("finance.view"):
            progs.append(_item("Donors & locations", "bi-geo-alt", "registers.index", "Registers"))
        people = []
        if can("staff.view"):
            people.append(_item("Staff directory", "bi-person-vcard", "staff.index", "Staff", match="staff."))
        if can("departments.view"):
            people.append(_item("Departments", "bi-diagram-3", "departments.index", "Depts", match="departments."))
        if can("leave.request") or can("leave.approve"):
            people.append(_item("Leave", "bi-airplane", "leave.index", "Leave", match="leave."))
        if can("attendance.record"):
            people.append(_item("Attendance", "bi-clipboard-check", "attendance.register", "Attendance"))
        access = []
        if can("users.view"):
            access.append(_item("Users", "bi-people", "workspace.users", match="workspace.user"))
        if can("roles.view"):
            access.append(_item("Roles & permissions", "bi-shield-lock", "workspace.roles", "Roles", match="workspace.role"))
        gov = []
        if can("audit.view"):
            gov.append(_item("Audit log", "bi-journal-text", "workspace.audit_log", "Audit"))
        if can("support.view"):
            gov.append(_item("HOLIDO support access", "bi-life-preserver", "workspace.support", "Support",
                             match="workspace.support"))
        if can("organization.view"):
            gov.append(_item("Organization settings", "bi-building-gear", "workspace.settings", "Settings"))
        groups = [("Workspace", home), ("Office", office), ("Programmes & projects", progs), ("People", people), ("Access", access),
                  ("Organization", gov)]
        # Phone tabs: the most-used destinations this person can open.
        by_ep = {i["endpoint"]: i for grp in groups for i in grp[1]}
        for ep in ("workspace.dashboard", "tasks.index", "projects.index", "comms.calendar", "programmes.index", "documents.index",
                   "meetings.index", "staff.index"):
            if ep in by_ep and len(tabs) < 4:
                tabs.append(by_ep[ep])
    elif current_user.is_platform_staff:
        admin = current_user.platform_role in (PlatformRole.SUPER_ADMIN, PlatformRole.PLATFORM_ADMIN)
        tenants = [_item("Organizations", "bi-buildings", "platform.organizations", "Orgs", match="platform.organization")]
        if admin:
            tenants.append(_item("Subscription plans", "bi-credit-card-2-front", "platform.plans", "Plans",
                                 match="platform.plan"))
        adm = []
        if current_user.is_super_admin:
            adm.append(_item("Platform staff", "bi-person-badge", "platform.staff", "Staff"))
        adm.append(_item("Audit log", "bi-journal-text", "platform.audit_log", "Audit"))
        home = [_item("Platform dashboard", "bi-speedometer2", "platform.dashboard", "Home")]
        groups = [("HOLIDO platform", home), ("Tenants", tenants), ("Administration", adm)]
        tabs = (home + tenants + adm)[:4]

    acct = [_item("My profile", "bi-person-circle", "account.profile", "Profile"),
            _item("Change password", "bi-key", "account.change_password", "Password"),
            _item("Two-step sign-in", "bi-shield-check", "account.two_factor", "2-step", match="account.two_factor")]
    if len(current_user.active_memberships()) > 1 or (current_user.is_platform_staff and current_user.active_memberships()):
        acct.insert(0, _item("My workspaces", "bi-collection", "account.workspaces", "Spaces"))
    if current_user.is_platform_staff and g.get("tenant") is not None:
        acct.insert(0, _item("HOLIDO console", "bi-speedometer2", "platform.dashboard", "Console"))
    groups.append(("My account", acct))
    if not tabs:
        tabs = acct[:3]
    groups = [(title, items) for title, items in groups if items]
    return {"groups": groups, "tabs": tabs}
