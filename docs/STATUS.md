# OIMS development status

_Last updated: 15 November 2026 — release 0.2.0-phase2_

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

110 automated tests pass on SQLite and on PostgreSQL 16. The Phase 2 migration was tested by upgrading
a Phase 1 database that already had users, checking that it matches the code exactly, downgrading and
upgrading again. Every page was crawled in Chrome at 320, 360, 390, 402 (iPhone 18 Pro), 440 (iPhone 18
Pro Max) and 1440 px in light and dark mode with no sideways scrolling, light patches, low-contrast text
or console/security-policy errors.

## Outstanding phases

| Phase | Scope |
|---|---|
| 3 — Programmes | Registration, planning, workplans, budgets, activities, indicators, reports |
| 4 — Projects | Registration, WBS, milestones, deliverables, budgets, risks, closure, programme links, Gantt charts |
| 5 — MEAL & beneficiaries | Results frameworks, data collection, beneficiaries, consent, feedback |
| 6 — Finance, procurement, assets | Budgets, expenditure, approvals, procurement, suppliers, assets |
| 7 — Reporting & analytics | Dashboards, charts, PDF/Excel/CSV exports |
| 8 — SaaS billing | Invoices, payment provider integration, renewals, usage enforcement |
| 9 — Hardening & launch | Security review, load testing, production backups, go-live |

## Known limitations of this release

- **Email** is real SMTP but optional; without it, notifications are in-app only and invitation links
  are shown once to the administrator.
- **Programme and project calendars** arrive with Phases 3 and 4 (the calendar already has the slots).
- **Meeting reports and letters print to PDF from the browser**; generated PDF/Excel exports come in Phase 7.
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
