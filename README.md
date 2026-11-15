# OIMS — Office Information Management System

A multi-tenant SaaS platform owned and operated by **HOLIDO — Holistic Development Organization**.

**Current release:** `0.7.0-phase7` (Phase 7 — Reporting and analytics). See [CHANGELOG.md](CHANGELOG.md) and
[docs/STATUS.md](docs/STATUS.md) for what is complete and what comes next.

## What Phase 7 adds

| Area | Delivered |
|---|---|
| Reports centre | Ten standard reports: portfolio summary, indicator performance, budget and spending, donor funding, activities, beneficiaries reached, feedback and complaints, procurement, assets, staff and leave |
| Filters | Period (from–to), programme or project (with or without its projects), department where it applies |
| Charts | Bar and monthly column charts with hover and keyboard tooltips, compact labels, one validated colour per light/dark mode, and the full table under every chart |
| Exports | Every report as Excel (summary + one sheet per table), CSV (per table) and PDF (summary, charts and tables); every export is logged |
| Same rules as the pages | A report only uses records the person may see; sensitive feedback is counted but never detailed; people and money are never counted twice |
| Safer spreadsheets | Text that looks like a spreadsheet formula is neutralised in all Excel and CSV exports |

## What Phase 6 adds

| Area | Delivered |
|---|---|
| Finance overview | Budget, spent, committed and available across the programmes and projects you can see (no double counting); everything waiting for your approval; goods received but not yet paid |
| Purchase requests | Raised against a budget line of an approved or active programme or project; items with estimates; approved by someone other than the requester only if the money is available |
| Buying rules | Thresholds per organization: one quotation, three quotations, or a competitive tender with an evaluation report; a written reason when the lowest quotation is not chosen |
| Purchase orders | Prepared from the chosen quotation (never above it); approved by finance, which commits the money on the budget line; cancelling releases it |
| Goods received | Partial or full deliveries with condition; recorded by the procurement office or the requester; items marked as assets go straight into the asset register |
| Payments | Never more than the value received; approved by a second person on the existing finance page; each payment releases the matching commitment; the order closes when received and paid in full |
| Suppliers | Register with category, contacts, tax ID and encrypted bank account; suspend or blacklist with a reason; performance rating |
| Asset register | Tags, categories, serials, cost, straight-line depreciation and book value, funding programme/project and donor, location, custodian, condition; assignment and return, transfers, maintenance and repairs, yearly physical checks, loss reports; disposal requested by one person and approved by another; Excel export; "in my care" for every staff member |
| Project closure | Two new checks: no open purchase orders, and project assets handed over (transferred or disposed) |

## What Phase 5 adds

| Area | Delivered |
|---|---|
| Beneficiary register | One record per person (`BEN/2026/0001`), sex, age or age group, disability, place, household; search and filters by programme/project, sex, age group, place |
| Privacy | Phone and ID numbers encrypted in the database; personal details visible only with a separate permission and every view logged; Excel export with or without personal details (logged); people who exit or withdraw consent can be anonymized while totals stay correct |
| Consent | What the person agreed to, how, and who gave it (a parent or guardian for children); withdrawal blocks anything new being recorded |
| Duplicates | Warning on likely matches (same phone, same ID number, or same name and birth year) before registering; merging two records moves everything to one |
| Enrolment & services | Enrol people in programmes and projects; record services and items received; named attendance for activity sessions |
| People reached | Each person counted once, also across a programme and its projects; by sex, age group and disability; included in reports (screen, Excel, PDF) |
| Data collection | Build simple forms (text, numbers, dates, choices, yes/no), publish, fill in, have answers checked by a second person, see summaries, export to Excel |
| Feedback & complaints | Record feedback from any channel; reply deadlines by priority; assign, respond, close with a satisfaction check; reminders; sensitive reports (safeguarding, fraud, misconduct) seen only by safeguarding staff; optional public page for communities, anonymous if they wish |
| MEAL overview | Beneficiaries by sex and age, people reached per programme and project, results and answers waiting to be checked, feedback response times and satisfaction |

## What Phase 4 adds

| Area | Delivered |
|---|---|
| Project registration | Separate **Projects** module with its own menu, list, codes (`PRJ/2026/001`) and permissions; title, objectives, justification, expected outcomes and outputs, locations, donor and funding source, dates, manager, team, budget, status workflow, documents |
| Independent or linked | A project can stand alone or belong to a programme; the project list filters by programme or "independent" |
| Planning & work breakdown | Proposal summary and resource plan; project → components → activities → tasks → subtasks, with deliverables shown where they belong |
| Deliverables | Acceptance criteria, due date, responsible person; submitted by the responsible person and accepted or returned by someone else; files attached |
| Risks & issues | Risk register (likelihood × impact rating, risk matrix, owner, review date); issue register; corrective actions assigned as tasks. Also available on programmes |
| Shared with programmes | Results framework, indicators, workplans, activities, milestones, timeline, budget and expenditure, monitoring, evaluations and reports all work for projects |
| Closure | Computed checklist (deliverables, activities, tasks, pending payments, open commitments, issues, unchecked results, final report and reconciliation); approval by someone other than the manager; the closed project becomes a read-only archive |
| Roll-up into programmes | Programme overview and reports list linked projects with combined budget and spending; project indicators can count toward a programme indicator. Every payment and result is recorded once, so nothing is counted twice |
| Everywhere else | Project tasks in Tasks, deliverable and risk-review dates in the calendar, dashboard and reminders; "Projects" in the menu and phone tab bar |

## What Phase 3 adds

| Area | Delivered |
|---|---|
| Programme registration | ID (automatic `PRG/2026/001` or your own), description, background, rationale, goal, sector, target population, coverage, dates and duration, manager, lead department, team, currency, approved budget, status workflow (draft → planned → approved → active → completed → closed, plus on hold / cancelled), documents |
| Planning | Strategy, implementation plan, theory of change, assumptions, risks; annual / quarterly / monthly workplans with approval; milestones; timeline (Gantt) chart |
| Results & indicators | Logical framework (goal → objectives → outcomes → outputs) with assumptions; indicators with baseline, targets per period, means of verification, data source, frequency, disaggregation by sex / age / disability; results reported by field staff and verified by someone else; no double counting |
| Implementation | Activities linked to workplans, outputs, budget lines and locations; responsible person, progress, actual dates; activity reports with participants (female/male, young people, disability), challenges and recommendations, photos and attendance sheets as attachments |
| Finance | Budget lines by category; budget editable until approval, then only through approved revisions; funding agreements and receipts per donor; expenditure and commitments with **separate approval** (the recorder can never approve); available balance, utilization and variance by line and category |
| Monitoring & learning | Monitoring visits, evaluations (baseline, mid-term, final…), lessons learned and recommendations with management responses |
| Reporting | Monthly, quarterly, semi-annual, annual, donor and performance reports: narrative + automatic figures, approval by someone other than the author, figures frozen on approval; PDF and Excel export; quick status report for any period |
| Registers | Donors and funding partners, locations, budget categories (shared with Phase 4 projects) |

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
                     meetings, tasks, comms (notifications, announcements, messages, calendar),
                     programmes and projects (+ programme_finance, programme_reports,
                     project_extras, owner_meal and registers), beneficiaries, meal (overview and
                     data collection), feedback (+ public page), finance (overview), procurement, assets,
                     analytics (reports centre)
  storage.py         local-disk and S3 file storage, upload checks
  notify.py          notifications, reference numbers   reminders.py  scheduled reminders
  twofactor.py       two-step sign-in
  programme_logic.py programme/project access, finance, indicator, roll-up and timeline calculations
  exporting.py       report figures, Excel and PDF exports
  meal_logic.py      beneficiary and feedback access, duplicate checks, people-reached counts
  crypto.py          encryption of personal data and keyed indexes for duplicate checks
  procurement_logic.py  purchase and asset access rules, buying method, order and payment figures
  analytics.py       the standard reports (one data structure per report)
  analytics_export.py   CSV, Excel and PDF versions of a report; spreadsheet formula protection
  templates/ static/ interface (Bootstrap 5 self-hosted; css/app.css, dark.css, mobile.css)
migrations/          Alembic migrations
tests/               176 automated tests
docs/                architecture, deployment, status
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — multi-tenancy, permissions, support access, how to add a module
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — environment variables, Render, Super Admin setup, backups, maintenance
- [docs/STATUS.md](docs/STATUS.md) — completed features, outstanding phases, known issues
