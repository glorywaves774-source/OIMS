# OIMS development status

_Last updated: 15 November 2026 — release 0.3.0-phase3_

## Phase 1 — Foundation ✅ complete

Platform structure, PostgreSQL and migrations, authentication, HOLIDO Super Admin setup, organization
registration and approval, tenant isolation, roles and permissions, HOLIDO support access, subscription
plans, audit log, interface (dark mode, phone layout).

## Phase 2 — Office information management ✅ complete

| Item | Status |
| --- | --- |
| Departments | Done |
| Staff register, directory and HR records (training, reviews, transfers, exit, staff file) | Done |
| Leave types, requests, approvals, balances | Done |
| Attendance register | Done |
| Documents: folders, categories, versions, approval, sharing, expiry, archive, download history | Done |
| File storage: persistent disk or S3-compatible; content checks; plan quotas | Done |
| Correspondence: register, reference numbers, routing, approval, deadlines, archive | Done |
| Meetings: scheduling, invitations, attendance, minutes, decisions, action points, report | Done |
| Tasks: assignment, priorities, deadlines, status, comments, attachments | Done |
| Notifications, announcements, internal messages | Done |
| Calendar: personal, departmental, organizational | Done |
| Scheduled reminders | Done |
| Two-step sign-in (required for HOLIDO staff) | Done |
| Department / own-record permission scopes | Done |
| Dashboard with office widgets | Done |

Phase 2 migration tested by upgrading a Phase 1 database with existing users, then downgrading and upgrading again.

## Phase 3 — Programmes management ✅ complete

| Item | Status |
| --- | --- |
| Programme registration, profile, team, status workflow, documents | Done |
| Planning: strategy, implementation plan, theory of change, assumptions, risks | Done |
| Workplans (annual / quarterly / monthly) with approval; milestones; timeline chart | Done |
| Results framework / logical framework | Done |
| Indicators: baselines, period targets, disaggregation, verification, double-counting guard | Done |
| Activities: assignment, budget, location, progress, activity reports with participants | Done |
| Finance: budget lines, revisions, funding agreements and receipts, expenditure and commitments with separate approval, variance | Done |
| Monitoring visits, evaluations, lessons learned, recommendations, management responses | Done |
| Reports: monthly to annual, donor and performance; approval with frozen figures; PDF and Excel | Done |
| Registers: donors, locations, budget categories | Done |
| Calendar, dashboard and reminders for activities, milestones and reports | Done |

126 automated tests pass on SQLite and on PostgreSQL 16. Migration `0003` was tested by upgrading a
Phase 2 database with existing data, checking it matches the code, downgrading and upgrading again.
Every programme page was crawled in Chrome at 320–440 px phone widths and 1440 px, in light and dark
mode, with no sideways scrolling, contrast problems or console/security-policy errors.

## Phase 4 — Project management ✅ complete

| Item | Status |
| --- | --- |
| Separate Projects module: register, codes, profile, team, status workflow, documents | Done |
| Independent projects and projects linked to a programme | Done |
| Planning, proposal summary, resource plan; workplans, activities, milestones, timeline | Done |
| Work breakdown structure: components → activities → tasks → subtasks, with deliverables | Done |
| Deliverables with acceptance criteria and checking by a second person | Done |
| Risk register, risk matrix, issue register and corrective actions (projects and programmes) | Done |
| Project budget, expenditure, results, indicators, monitoring and reports (shared design) | Done |
| Closure checklist, closure report, independent approval, read-only archive | Done |
| Roll-up into programmes without double counting (finance, indicators, reports) | Done |
| Tasks, calendar, dashboard, reminders and navigation include projects | Done |

140 automated tests pass on SQLite and on PostgreSQL 16. Migration `0004` was tested by upgrading a
Phase 3 database with existing programmes, activities and tasks, checking it matches the code,
downgrading and upgrading again. Every project page was crawled in Chrome at 320–440 px phone widths
and 1440 px, in light and dark mode, with no sideways scrolling, contrast problems or console errors.

## Phase 5 — MEAL & beneficiaries ✅ complete

| Item | Status |
| --- | --- |
| Beneficiary register, households, search and filters | Done |
| Encrypted personal details, separate permission, logged views, controlled export | Done |
| Consent (including parent/guardian for children) and withdrawal | Done |
| Duplicate warnings and merging | Done |
| Enrolment in programmes and projects; services; named activity attendance | Done |
| People reached, each counted once across programmes and their projects; in reports | Done |
| Data-collection forms: design, publish, collect, second-person check, summary, Excel | Done |
| Feedback and complaints: channels, deadlines, assignment, response, closure, satisfaction, reminders | Done |
| Confidential handling of safeguarding, fraud and misconduct reports | Done |
| Optional public feedback page with anonymous option | Done |
| MEAL overview dashboard; new Safeguarding Focal Point role | Done |

156 automated tests pass on SQLite and on PostgreSQL 16. Migration `0005` was tested by upgrading a
Phase 4 database with existing projects, activities and activity reports, checking it matches the code,
downgrading and upgrading again. Every new page — including the public feedback page — was crawled in
Chrome at 320–440 px phone widths and 1440 px, in light and dark mode, with no sideways scrolling,
contrast problems or console errors.

## Outstanding phases

| Phase | Scope |
|---|---|
| 6 — Finance, procurement, assets | Budgets, expenditure, approvals, procurement, suppliers, assets |
| 7 — Reporting & analytics | Dashboards, charts, PDF/Excel/CSV exports |
| 8 — SaaS billing | Invoices, payment provider integration, renewals, usage enforcement |
| 9 — Hardening & launch | Security review, load testing, production backups, go-live |

## Known limitations of this release

- **Email** is real SMTP but optional; without it, notifications are in-app only and invitation links
  are shown once to the administrator.
- **Programme roll-up of money** adds projects in the programme's currency; projects in another
  currency are listed but not added (no exchange rates yet).
- **Indicator roll-up** applies to indicators that add up (counts). Rates and percentages are not
  combined across projects, because averaging them would be misleading.
- **Closure checklist** cannot yet check asset handover or procurement; those records arrive in Phase 6,
  so the closure report has a written "handover of assets" section meanwhile.
- **Head-counts and named attendance are separate**: an activity report's head-count can include people
  who are not registered; "people reached" counts only registered beneficiaries, each once.
- **Data collection works online**: forms are filled in the browser with a connection. Offline collection
  on phones (and import from KoBo/ODK) is not included yet.
- **Form answers do not feed indicators automatically**; a MEAL officer reports the indicator result from
  the summary.
- **Public feedback page** has a hidden bot trap and a rate limit but no CAPTCHA.
- **Encryption key** is derived from `SECRET_KEY`; changing it makes encrypted phone and ID numbers
  unreadable (see DEPLOYMENT.md).
- **Exchange rates**: each programme has one currency; multi-currency conversion is not supported yet.
- **Report charts**: PDF/Excel exports contain tables, not charts; organization-wide dashboards and
  more export formats come in Phase 7.
- **Meeting minutes and letters print to PDF from the browser** (no generated PDF yet).
- **Messages and notifications refresh when the page loads** (no live push yet).
- **Leave entitlements** are per calendar year, without carry-over or accrual rules; public holidays
  are not yet excluded from working-day counts.
- **Document search** looks at titles and descriptions, not inside file contents.
- **Persistent disk storage** limits the web service to one instance; switch to S3-compatible storage to scale.
- **Rate limits** use per-process memory by default; set `RATELIMIT_STORAGE_URI` to Redis when running
  several instances.
- **Subscriptions** do not yet block access when expired (Phase 8).
- **Help assistant** (chatbot) and **French / other languages** are not included yet.
- Phone layouts were checked with Chrome's phone emulation, which is not identical to Safari on a real
  iPhone; a quick check on real devices is recommended.
