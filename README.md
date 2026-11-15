# OIMS — Office Information Management System

A multi-tenant SaaS platform owned and operated by **HOLIDO — Holistic Development Organization**.

**Current release:** `0.2.0-phase2` (Phase 2 — Office information management). See [CHANGELOG.md](CHANGELOG.md) and
[docs/STATUS.md](docs/STATUS.md) for what is complete and what comes next.

## What Phase 2 adds

| Area | Delivered |
|---|---|
| Departments | Create, close/reopen, head of department, responsibilities, staff and activity per department |
| Staff & HR | Staff register (with or without an OIMS sign-in), directory, employment details, emergency contacts, HR notes, training, performance reviews, transfers (automatic when the department changes), exit with clearance and sign-in suspension, staff documents |
| Leave & attendance | Configurable leave types and entitlements, requests counted in working days, overlap and balance checks, approval by department head or HR, who's-away list; daily attendance register |
| Documents | Folders, categories, versions, approval workflow, sharing (everyone / department / chosen people), expiry dates, archive, download history, storage quotas; files checked by content and kept on a persistent disk or S3-compatible storage |
| Correspondence | Incoming, outgoing and memos with automatic reference numbers (IN/2026/0001), assignment, forwarding with instructions, approval, reply deadlines, confidentiality, attachments, routing history, archive |
| Meetings | Scheduling in the organization's time zone, invitations and responses, agenda, attendance, minutes, decisions, action points that become tasks, printable report |
| Tasks | Assignment, priorities, deadlines, status, comments, attachments, overdue highlighting |
| Communication | In-app notifications (plus email when configured), announcements to everyone or a department, private internal messages |
| Calendar | Personal, departmental and organizational month view and agenda: meetings, deadlines, leave, expiring documents |
| Reminders | Hourly job for due/overdue tasks, upcoming meetings, expiring documents and reply deadlines — each sent once |
| Security | Two-step sign-in with authenticator apps and recovery codes (required for HOLIDO staff), admin reset; department-level and own-record permission scopes now enforced |

## What Phase 1 provides

| Area | Delivered |
|---|---|
| Platform structure | Flask application factory, blueprints per area, environment-based configuration, PostgreSQL via SQLAlchemy 2 + Alembic migrations |
| HOLIDO Super Admin | Secure first-run setup (token-protected web page **or** CLI from environment variables); platform console with live statistics; platform staff management (Super Admin, Platform Administrator, Support Officer) |
| Organizations (tenants) | Public registration with HOLIDO approval; direct creation by HOLIDO; approve / reject / suspend / activate / deactivate with reasons; profile, logo, currency, fiscal year, time zone |
| Tenant isolation | Automatic per-request data scoping on every tenant table, write guards that refuse cross-tenant writes, explicit tenant checks in routes, 404 (not 403) for other organizations' records |
| Users & access | Global accounts with per-organization memberships; invitations; suspend / reactivate / remove; last-administrator protection; one person can belong to several organizations |
| Roles & permissions | 15 standard roles from the specification, custom roles, permissions by **module · action · scope** (organization / department / own records), least privilege by default |
| Support access | HOLIDO staff request time-limited (≤ 2 h), **read-only** access with a reason; organization approves, denies or revokes; every page viewed is logged in the organization's audit log |
| Subscriptions (foundation) | Plans with prices, trial days, user and storage limits; assignment per organization; user limit enforced. Online billing is Phase 8. |
| Security | scrypt password hashing, password policy, account lockout, rate limiting, CSRF, strict Content-Security-Policy (no inline scripts), secure cookies, session invalidation on password change, signed single-use reset links, open-redirect protection, logo uploads validated by content |
| Audit | Append-only audit log of sign-ins, failures, lockouts, administrative and support actions — platform-wide and per organization |
| Interface | Spatial "glass" design, dark / light mode on every page, phone layout with slide-in menu and bottom tab bar, collapsible desktop sidebar, confirmation dialogs, empty states |

## Quick start (local)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then edit SECRET_KEY and DATABASE_URL
flask --app wsgi db upgrade     # create tables
```

Create the first HOLIDO Super Admin — **choose one** method:

```bash
# a) CLI (reads OIMS_SUPERADMIN_EMAIL / OIMS_SUPERADMIN_PASSWORD; password must be changed at first sign-in)
flask --app wsgi oims create-superadmin

# b) Web: set OIMS_SETUP_TOKEN in .env, start the app, open /setup and enter the token
```

Run:

```bash
flask --app wsgi run --debug        # development
gunicorn wsgi:app                   # production-style
```

Run the tests:

```bash
pytest                                                    # SQLite in memory
TEST_DATABASE_URL=postgresql+psycopg://user:pw@localhost/oims_test pytest   # real PostgreSQL
```

## Deploying to Render

`render.yaml` defines a web service and a managed PostgreSQL database. Migrations run automatically
before each deploy (`preDeployCommand`). Full instructions, including backups and the Super Admin
initialization, are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Project layout

```
app/
  __init__.py        application factory, hooks, error pages
  config.py          environment-based settings
  models/            identity (users, organizations, memberships, roles) and platform records
  tenancy.py         tenant isolation guard
  rbac.py            permission catalog, standard role templates, permission checks
  security.py        password policy, tokens, headers, email
  services.py        business operations (registration, approval, invitations…)
  navigation.py      sidebar and phone tab bar per person
  blueprints/        public, auth, setup, account, platform (HOLIDO), workspace (/o/<org>),
                     people (departments, staff, leave, attendance), documents, correspondence,
                     meetings, tasks, comms (notifications, announcements, messages, calendar)
  storage.py         local-disk and S3 file storage, upload checks
  notify.py          notifications, reference numbers   reminders.py  scheduled reminders
  twofactor.py       two-step sign-in
  templates/ static/ interface (Bootstrap 5 self-hosted; css/app.css, dark.css, mobile.css)
migrations/          Alembic migrations
tests/               110 automated tests
docs/                architecture, deployment, status
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — multi-tenancy, permissions, support access, how to add a module
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — environment variables, Render, Super Admin setup, backups, maintenance
- [docs/STATUS.md](docs/STATUS.md) — completed features, outstanding phases, known issues
