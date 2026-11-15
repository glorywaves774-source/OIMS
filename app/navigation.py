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


def build_nav():
    if not current_user.is_authenticated:
        return {"groups": [], "tabs": []}
    groups = []
    tabs = []
    if g.get("tenant") is not None:
        ws = [_item("Dashboard", "bi-grid-1x2", "workspace.dashboard", "Home")] if can("dashboard.view") else []
        people = []
        if can("users.view"):
            people.append(_item("Users", "bi-people", "workspace.users", match="workspace.user"))
        if can("roles.view"):
            people.append(_item("Roles & permissions", "bi-shield-lock", "workspace.roles", "Roles", match="workspace.role"))
        gov = []
        if can("audit.view"):
            gov.append(_item("Audit log", "bi-journal-text", "workspace.audit_log", "Audit"))
        if can("support.view"):
            gov.append(_item("HOLIDO support access", "bi-life-preserver", "workspace.support", "Support", match="workspace.support"))
        org = [_item("Organization settings", "bi-building-gear", "workspace.settings", "Settings")] if can("organization.view") else []
        groups = [("Workspace", ws), ("People & access", people), ("Governance", gov), ("Organization", org)]
        tabs = (ws + people + org + gov)[:4]
    elif current_user.is_platform_staff:
        admin = current_user.platform_role in (PlatformRole.SUPER_ADMIN, PlatformRole.PLATFORM_ADMIN)
        tenants = [_item("Organizations", "bi-buildings", "platform.organizations", "Orgs", match="platform.organization")]
        if admin:
            tenants.append(_item("Subscription plans", "bi-credit-card-2-front", "platform.plans", "Plans", match="platform.plan"))
        adm = []
        if current_user.is_super_admin:
            adm.append(_item("Platform staff", "bi-person-badge", "platform.staff", "Staff"))
        adm.append(_item("Audit log", "bi-journal-text", "platform.audit_log", "Audit"))
        home = [_item("Platform dashboard", "bi-speedometer2", "platform.dashboard", "Home")]
        groups = [("HOLIDO platform", home), ("Tenants", tenants), ("Administration", adm)]
        tabs = (home + tenants + adm)[:4]

    acct = [_item("My profile", "bi-person-circle", "account.profile", "Profile"),
            _item("Change password", "bi-key", "account.change_password", "Password")]
    if len(current_user.active_memberships()) > 1 or (current_user.is_platform_staff and current_user.active_memberships()):
        acct.insert(0, _item("My workspaces", "bi-collection", "account.workspaces", "Spaces"))
    if current_user.is_platform_staff and g.get("tenant") is not None:
        acct.insert(0, _item("HOLIDO console", "bi-speedometer2", "platform.dashboard", "Console"))
    groups.append(("My account", acct))
    if not tabs:
        tabs = acct[:3]
    groups = [(title, items) for title, items in groups if items]
    return {"groups": groups, "tabs": tabs}
