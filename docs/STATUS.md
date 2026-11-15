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

## Outstanding phases

| Phase | Scope |
|---|---|
| 5 — MEAL & beneficiaries | Results frameworks, data collection, beneficiaries, consent, feedback |
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
- **Beneficiary names in attendance**: activity reports record participant counts; named attendance
  linked to beneficiary records comes with Phase 5 (MEAL & beneficiaries). Attendance sheets can be
  attached as files meanwhile.
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
