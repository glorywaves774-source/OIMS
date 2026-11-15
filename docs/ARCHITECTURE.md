# OIMS architecture

## Hierarchy

```
HOLIDO platform (console at /platform)
└── Organizations / tenants (workspace at /o/<slug>)
    └── Departments → Programmes → Projects → Activities → Tasks   (Phases 2–4)
        (projects may also exist without a programme)
```

Platform pages and organization workspaces are separate blueprints with separate access rules.
Platform staff never enter a workspace except through support access.

## Identity model

- **User** — one global account per email. `platform_role` is set only for HOLIDO staff.
- **Organization** — a tenant. Status: `pending → active ⇄ suspended / deactivated`, or `rejected`.
- **Membership** — links a user to an organization with exactly one **Role**. Status: `pending`
  (registration awaiting approval), `invited` (no password yet), `active`, `suspended`.
- **Role** — belongs to one organization. `is_system` roles come from templates; `is_admin` roles hold
  every permission, including permissions added in later phases.
- **RolePermission** — `(role, permission_code, scope)`; scope is `organization`, `department` or `own`.

## Tenant isolation (app/tenancy.py)

Every tenant-owned model inherits `TenantMixin` (adds an indexed, non-null `organization_id`).
The workspace blueprint verifies the person's active membership (or a live support grant) and then
sets the tenant for the request. From that point:

1. **Reads** — a SQLAlchemy `do_orm_execute` hook adds `organization_id = <current>` to every
   SELECT touching a tenant model, including relationship loads and pagination counts.
2. **Writes** — a `before_flush` hook stamps new rows with the tenant and raises
   `TenantIsolationError` for rows created, changed, deleted or moved in another organization.
   Tenant rows can never be created without an organization.
3. **Routes** — `tenant_get_or_404()` filters explicitly as well. Records of other organizations
   return 404 so their existence is not revealed.
4. **Intentional cross-tenant reads** (e.g. a person's list of their own workspaces) must be marked
   with `unscoped(statement)`.

Tenant context is cleared at the start of every request.

## Permissions (app/rbac.py)

`CATALOG` lists modules and actions (`users.invite`, `audit.view`, …). Routes use
`@require_permission("users.invite")`; templates use `can("users.invite")` to hide actions people
cannot take. Navigation is built per person, so nobody sees modules they cannot open.

`ROLE_TEMPLATES` defines the 15 standard roles with wildcard patterns (`"programmes.*"`, `"*.view"`).
When a later phase adds modules to `CATALOG`, run `flask --app wsgi oims sync-roles` to grant the new
permissions to every organization's standard roles. Standard roles are read-only to organizations;
they duplicate one as a custom role to adjust it.

### Adding a module in a later phase

1. Add the module's actions to `CATALOG`.
2. Create models inheriting `TenantMixin` (and `TimestampMixin`); generate a migration.
3. Add a blueprint under `/o/<org_slug>/...` (or extend `workspace`) using `@require_permission`
   and `tenant_get_or_404`.
4. Add the menu entry in `navigation.py`, guarded by `can(...)`.
5. Add tests, including a cross-tenant access test.
6. Deploy, then run `oims sync-roles`.

## HOLIDO support access

1. Platform staff request access from the organization page, giving a reason and duration (30 min – 2 h).
2. If the organization requires approval (default), its administrators approve or deny in
   **HOLIDO support access**. Organizations may choose to waive approval in their settings.
3. The requester enters the workspace with **read-only** permissions; any non-GET request is refused.
4. Every page opened is written to the organization's audit log, flagged as support access.
5. Access ends at expiry, when the requester ends it, or when the organization revokes it.

## Audit log

`AuditLog` rows record actor, organization, action, entity, summary, IP and user agent. They are written
in the same transaction as the change they describe. The application has no code path that edits or
deletes audit rows.

## Front end

Self-hosted Bootstrap 5 and Bootstrap Icons, plus `app.css` (spatial design), `dark.css` (dark theme)
and `mobile.css` (loaded last, phones ≤ 760 px). `theme-init.js` runs synchronously in `<head>` to
apply the saved or device theme before the page draws. All behaviour is in `app.js`; the Content
Security Policy forbids inline scripts and styles.
