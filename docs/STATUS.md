# ZENTAVA development status

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

## Phase 6 — Finance, procurement and assets ✅ complete

| Item | Status |
| --- | --- |
| Organization finance overview with approval queue and payables | Done |
| Purchase requests with funds check and independent approval | Done |
| Procurement thresholds (one quote / three quotes / tender) and justified selection | Done |
| Purchase orders committing funds; cancellation releasing them | Done |
| Goods received (partial and full) creating asset records | Done |
| Payments limited to goods received, approved separately, releasing commitments | Done |
| Supplier register with encrypted bank details, blacklisting and rating | Done |
| Asset register: custody, transfers, maintenance, checks, depreciation, disposal approval, export | Done |
| Project closure checks for open orders and project assets | Done |
| New role: Logistics & Assets Officer; everyone can see the assets in their care | Done |

167 automated tests pass on SQLite and on PostgreSQL 16. Migration `0006` was tested by upgrading a
Phase 5 database with existing projects, budget lines and expenditure, checking it matches the code,
downgrading and upgrading again. Every new page was crawled in Chrome at 320–440 px phone widths and
1440 px, in light and dark mode, with no sideways scrolling, contrast problems or console errors.

## Phase 7 — Reporting and analytics ✅ complete

| Item | Status |
| --- | --- |
| Reports centre with ten standard reports across programmes, MEAL, finance, operations and office | Done |
| Period, programme/project and department filters | Done |
| Charts (bars and monthly columns) with tooltips and a table for every chart | Done |
| Excel, CSV and PDF exports, logged | Done |
| Permissions and scopes respected; no double counting of people or money | Done |
| Spreadsheet formula protection for all exports | Done |

176 automated tests pass on SQLite and on PostgreSQL 16. No database changes in this phase (the schema
check confirms the models match migration `0006`). Every report page was crawled in Chrome at 320–440 px
phone widths and 1440 px, in light and dark mode, with no sideways scrolling, contrast problems or console
errors. Chart colours were checked with a palette validator for both light and dark surfaces.

## Phase 8 — SaaS billing ✅ complete

| Item | Status |
| --- | --- |
| Automatic invoices before each period or trial end; invoice PDF; tax and invoice details set by HOLIDO | Done |
| Online payments through Paystack (card, mobile money) with server-side confirmation and signed webhooks | Done |
| Bank transfer / mobile money / cheque payments recorded by HOLIDO staff; part payments; invoice cancellation | Done |
| Renewal, plan changes (next period, or immediately in a trial), downgrade checks, cancel at period end | Done |
| Past due → grace period → read-only workspace (billing stays open) → restored on payment | Done |
| Usage meters for people and storage; user and storage limits enforced | Done |
| HOLIDO billing console and settings; hourly billing run with the reminders job | Done |

189 automated tests pass on SQLite and on PostgreSQL 16 (Paystack calls are simulated in tests). Migration
`0007` was tested by upgrading a Phase 7 database with an existing subscription, checking it matches the code,
downgrading and upgrading again. The billing pages (organization and HOLIDO side) were crawled in Chrome at
320–440 px phone widths and 1440 px, in light and dark mode, with no sideways scrolling, contrast problems or
console errors.

## ZENTAVA rebrand ✅ complete (0.8.1-zentava)

- Name ZENTAVA OIMS (two-tone wordmark), tagline, logo and colours from the ZENTAVA brand profile, in both themes, emails, PDFs and spreadsheets.
- Internal names kept (`flask oims`, `OIMS_*` variables) so deployment settings do not change.
- The logo is a vector redraw; HOLIDO can drop in the original artwork as `app/static/img/logo.svg`.
- Verified: 193 tests pass (SQLite; affected modules also on PostgreSQL); every menu page crawled at
  320/360/390/402/440/1440px in light and dark mode with no issues.

## Outstanding phases

| Phase | Scope |
|---|---|
| 9 — Hardening & launch | Security review, load testing, production backups, go-live |

## Known limitations of this release

- **Email** is real SMTP but optional; without it, notifications are in-app only and invitation links
  are shown once to the administrator.
- **Programme roll-up of money** adds projects in the programme's currency; projects in another
  currency are listed but not added (no exchange rates yet).
- **Indicator roll-up** applies to indicators that add up (counts). Rates and percentages are not
  combined across projects, because averaging them would be misleading.
- **Organization running costs** (rent, salaries outside programmes) are not budgeted yet: purchases must be
  charged to a programme or project budget line.
- **Paystack has not been tried against the live service from here** (the build environment cannot reach it);
  the integration follows Paystack's documented API and is covered by simulated tests. Do one test-mode
  payment after deployment (docs/DEPLOYMENT.md).
- **No mid-period upgrades with pro-rated charges**: a plan change applies from the next period. HOLIDO can
  still change a plan immediately from the organization's page.
- **Invoices in the plan's currency only**; no automatic currency conversion or card-on-file auto-renewal.
- **Reports are produced on request**: there are no scheduled report emails and no custom report builder yet.
- **Large organizations**: reports are calculated when opened; with many thousands of records some may take a
  few seconds. Caching can be added in Phase 9 if needed.
- **Payments are recorded, not made**: ZENTAVA does not connect to banks or mobile money.
- **One currency per order**; the finance overview shows a total per currency without conversion.
- **Asset tags** are numbers (AST/2026/0001); printing labels or QR codes is not included yet.
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
- **Charts in Excel**: Excel exports contain the tables (ready for your own charts); PDFs include the charts.
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
