# OIMS development status

_Last updated: 15 November 2026 — release 0.1.0-phase1_

## Phase 1 — Foundation ✅ complete

| Item | Status |
| --- | --- |
| Project structure, configuration, WSGI entry point | Done |
| PostgreSQL database and migrations | Done; verified on PostgreSQL 16 |
| Authentication (sign-in, sign-out, lockout, rate limits, sessions) | Done |
| Password policy, change, reset, invitation links | Done |
| HOLIDO Super Admin first-run setup (web + CLI) | Done |
| Organization registration, approval, status changes | Done |
| Tenant isolation (data layer + routes) | Done |
| Roles and permissions (15 standard + custom, module · action · scope) | Done |
| HOLIDO support access (approved, read-only, time-limited, logged) | Done |
| Subscription plans (definition, assignment, user limits) | Done |
| Audit log (platform + organization views) | Done |
| Interface: dark mode, phone layout, menus, confirmation dialogs | Done |

63 automated tests pass on SQLite and PostgreSQL. Every page was also crawled in Chrome at 320, 360,
390, 402 (iPhone 18 Pro), 440 (iPhone 18 Pro Max) and 1440 px, in light and dark mode, with no
sideways scrolling, light patches in dark mode, low-contrast text or console/CSP errors.

## Outstanding phases

| Phase | Scope |
|---|---|
| 2 — Office information management | Staff/HR, departments, documents (object storage), correspondence, meetings, calendar, tasks, messaging |
| 3 — Programmes | Registration, planning, workplans, budgets, activities, indicators, reports |
| 4 — Projects | Registration, WBS, milestones, deliverables, budgets, risks, closure, programme links |
| 5 — MEAL & beneficiaries | Results frameworks, data collection, beneficiaries, consent, feedback |
| 6 — Finance, procurement, assets | Budgets, expenditure, approvals, procurement, suppliers, assets |
| 7 — Reporting & analytics | Dashboards, charts, PDF/Excel/CSV exports |
| 8 — SaaS billing | Invoices, payment provider integration, renewals, usage limits |
| 9 — Hardening & launch | Security review, load testing, production backups, go-live |

## Known limitations of this release

- **No two-factor authentication yet.** Recommended for HOLIDO staff before launch; planned for Phase 2.
- **Email** is real SMTP but optional; without it, links are shown once to the administrator.
- **Rate limits** use per-process memory by default; set `RATELIMIT_STORAGE_URI` to Redis when
  running several instances.
- **Department and own-record scopes** are stored on permissions now but only take effect when
  departments and record ownership arrive in Phase 2.
- **Subscriptions** do not yet block access when expired; enforcement arrives with billing (Phase 8).
- **Help assistant** (chatbot) and **French / other languages** are not included yet.
- Phone layouts were checked with Chrome's phone emulation, which is not identical to Safari on a
  real iPhone; a quick check on real devices is recommended.
