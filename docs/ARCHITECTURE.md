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

## Permission scopes (enforced from Phase 2)

Each permission is granted with a scope. `scoped()` and `in_scope()` in `app/blueprints/tenant.py`
apply it to lists and to single records:

| Scope | Lists show | Example |
|---|---|---|
| `organization` | everything in the organization | HR Officer: `staff.records` |
| `department` | records of the person's own department, plus their own | Department Head: `tasks.view`, `leave.approve` |
| `own` | records the person created or is assigned to | Staff Member: `tasks.view`, `meetings.view` |

A person's department comes from their staff record (`StaffProfile.user_id`). Extra rules on top:

- **Documents**: visible to the owner, to everyone / the department / chosen people once approved,
  and to approvers while pending; attachments inherit the visibility of the record they belong to
  (staff file → HR records access; task, meeting, letter → whoever can see that record).
- **Correspondence**: confidential items are visible only to the people handling them and to
  `correspondence.manage`.
- **Messages** are visible only to the participants — not to administrators or HOLIDO support.
- **HR records** (contracts, emergency contacts, leave, attendance, training, reviews, exit) need
  `staff.records`; everyone with `staff.view` sees only the directory entry. People always see their own.

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

## Programmes (Phase 3)

```
Programme ─┬─ ResultNode (goal → objective → outcome → output) ─ Indicator ─┬─ IndicatorTarget (per period)
           │                                                               └─ IndicatorResult (reported → verified)
           ├─ Workplan ─ Activity ─┬─ ActivityReport (participants, challenges)
           │                       └─ Expenditure (optional link)
           ├─ Milestone
           ├─ BudgetLine (by BudgetCategory) ─┬─ Expenditure / commitment (pending → approved)
           │                                  └─ BudgetRevisionLine ← BudgetRevision (pending → approved)
           ├─ FundingAgreement (Donor) ─ FundingReceipt
           ├─ MonitoringVisit · Evaluation · LearningItem (lesson / recommendation + management response)
           ├─ ProgrammeReport (narrative + snapshot frozen on approval)
           └─ ProgrammeTeamMember
```

- **Ready for projects.** Results, indicators, activities, budget lines and expenditure carry a nullable
  `programme_id`; Phase 4 adds `project_id` to the same tables, so a project inside a programme and an
  independent project use the same structures.
- **Scope for programmes.** "Own" means the person manages the programme or is on its team; "department"
  means the programme's lead department. `programme_logic.allowed()` applies this for every action.
- **Indicators.** `aggregation` decides how results combine: `sum` (counts per period are added),
  `latest` (rates/percentages: most recent period) or `max`. Only verified results count. For `sum`
  indicators the same period and place cannot be reported twice — this is the double-counting guard.
  Progress = (result − baseline) ÷ (target − baseline), so it works for indicators that should go down.
- **Separation of financial duties.** Expenditure, commitments and budget revisions are recorded by one
  person and approved by another with `finance.approve`; the app refuses self-approval. Approval is also
  refused if it would exceed what is left on the budget line. After a programme is approved its budget
  lines are locked and change only through an approved revision.
- **Reports.** `exporting.report_data()` builds one dictionary used by the screen, the Excel workbook
  and the PDF. When a report is approved that dictionary is stored as `snapshot`, so approved reports
  never change when later data is entered.

## Projects (Phase 4)

```
Programme (optional) ─ Project ─┬─ Component ─ Activity ─ Task ─ Task (subtask)
                                ├─ Deliverable (pending → submitted → verified / rejected; or cancelled)
                                ├─ RiskItem ─ Issue ─ Task (corrective action, issue_id / risk_id)
                                ├─ ProjectClosure (checklist snapshot frozen on approval)
                                └─ the shared programme tables, through project_id
```

- **Separate modules, shared design.** `programmes_bp` and `projects_bp` are two blueprints. Each view is
  registered on both by `@route`; `K()` says which one is serving the request. A record belongs to
  exactly one owner: shared tables carry `programme_id` *or* `project_id`. Helpers in `programme_logic`
  (`own`, `of`, `owner_of`, `pcode`) hide the difference, and `pcode` turns `programmes.edit` into
  `projects.edit` so each module keeps its own permissions.
- **Archived records.** `can_do()` refuses every change on a closed or cancelled programme or project.
  The only exception is the status change that revives a cancelled record (`can_set_status`). A project
  is closed only by approving its closure, never by picking "closed" from the status list.
- **Independent approval.** Plans and closures cannot be approved by the manager unless their
  `manage` permission covers the whole organization; closures also need someone other than the submitter.
- **Roll-up without double counting.** `consolidated(programme)` adds the programme's own budget and
  spending to its linked projects'. Each expenditure has one owner, so the sums cannot overlap. A project
  indicator may set `contributes_to_id` to a summing indicator of its own programme;
  `indicator_actual()` then includes the project's verified results in the programme figure. The result
  is stored once, on the project indicator.
- **Tasks.** A task with `project_id` (or linked to an issue or risk) is visible to anyone who can see
  that project or programme, and becomes read-only when it is archived.

## Notifications and reminders

`app/notify.py::notify()` writes one in-app notification per recipient and emails those who allow it
(when SMTP is configured). Reminders (`app/reminders.py`) use a de-duplication key per item and person.
Reference numbers come from `SequenceCounter` rows, locked with `SELECT … FOR UPDATE` on PostgreSQL so
two people registering letters at the same moment cannot get the same number.

## Files

`app/storage.py` validates every upload by content (magic bytes / Office zip structure), stores it
under `org-<id>/<random>` on a local disk or S3-compatible store, and records size and SHA-256 in
`DocumentVersion`. Downloads go through the app (permission check, access log, sandboxing CSP,
`Content-Disposition: attachment`). Plan storage limits are enforced on upload.

## Audit log

`AuditLog` rows record actor, organization, action, entity, summary, IP and user agent. They are written
in the same transaction as the change they describe. The application has no code path that edits or
deletes audit rows.

## Front end

Self-hosted Bootstrap 5 and Bootstrap Icons, plus `app.css` (spatial design), `dark.css` (dark theme)
and `mobile.css` (loaded last, phones ≤ 760 px). `theme-init.js` runs synchronously in `<head>` to
apply the saved or device theme before the page draws. All behaviour is in `app.js`; the Content
Security Policy forbids inline scripts and styles.
