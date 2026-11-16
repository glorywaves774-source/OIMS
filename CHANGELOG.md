# Changelog

## 0.9.2-fr — 16 November 2026

French.

- **EN / FR switch** on every page, including sign-in and the public page. The choice is kept on the person's
  account (or in a cookie for visitors).
- Every screen is available in French, with dates in French. What people type in (names, notes, records, the
  organization's name) is never translated.
- Also on this release line: the aurora background and the neumorphic sign-in page.

## 0.9.1-rates — 16 November 2026

Exchange rates.

- **Finance → Exchange rates**: the finance team records dated rates ("1 USD = 15.40 GHS from 1 November") with
  their source. Only roles allowed to *set exchange rates* can add or remove them; every change is in the audit log.
- **Combined totals in the organization's currency** on the finance overview, in programme roll-ups and reports
  (projects in other currencies are now included), and in the Budget and spending report.
- Spending in a period uses the rate of the day of each payment, so past reports keep their figures; a currency
  without a rate is left out and named, never guessed.

## 0.9.0-phase9 — 16 November 2026

Hardening and launch.

- **Security review.** Every page and action was tried signed out, as another organization's administrator and
  as a low-permission staff member; nothing leaked or changed that should not. Fixed:
  - the *Pay online* button would have been blocked by the browser (page security policy); the billing page now
    allows Paystack's checkout only;
  - a crafted sign-in link could send people to another website afterwards;
  - outgoing email did not check the mail server's certificate;
  - the health check showed the version number.
  The server now refuses to start with unsafe production settings. All packages are pinned to the tested
  versions and checked for known flaws (Pillow updated).
- **Speed with large organizations** (tested with 16,000 beneficiaries and 60 organizations): MEAL dashboard
  15 s → 0.6 s, finance overview 5 s → 0.4 s, procurement 3.6 s → 0.13 s, procurement report 10 s → 0.5 s,
  beneficiary export 38 s → 4 s with flat memory. Long finance lists show the oldest 50 with totals; open
  orders are paged. Large downloads take turns so everyone else stays quick.
- **Backups**: encrypted nightly off-site backups of the database and documents with a tested restore
  (`flask oims backup`, `backup-list`, `backup-verify`, `restore`, `backup-key`); new nightly Render job.
- **Go-live**: `flask oims check-deploy`, a going-live checklist and capacity guide in docs/DEPLOYMENT.md, web
  server settings for Render's 512 MB plan.

## 0.8.1-zentava — 15 November 2026

New name and brand: **ZENTAVA OIMS — Organized. Transparent. Accountable.**

- The product name is ZENTAVA OIMS on every page (a two-tone wordmark: ZENTAVA bold, OIMS in teal), in emails, PDFs, spreadsheets, notifications and the
  authenticator app label (new set-ups show "ZENTAVA OIMS"; existing codes keep working).
- New logo (navy bracket, gold bar, teal diamond) in the menu, on the sign-in and public pages and as the
  browser icon.
- Brand colours: deep navy, teal, gold and light grey, tuned for readability in light and dark mode.
- The public page shows the tagline, what ZENTAVA does and what the name stands for.
- New invoices are numbered ZTV-YYYY-NNNNN (the running number continues).
- Internal names (`flask oims` commands, `OIMS_*` settings) are unchanged, so nothing needs reconfiguring.
- **Provider**: ZENTAVA OIMS is provided by **Kayron Global Tech Services** (previously HOLIDO). The name
  appears on the public page, registration, billing, invoices and the platform console ("Kayron platform",
  "Kayron support access"). A database update switches the invoice company name if it still had the old
  default; invoices already issued keep the name they were issued with.

## 0.8.0-phase8 — 15 November 2026

SaaS billing.

- **Invoices** are issued automatically before each period or trial ends (PDF, numbered, tax if set).
- **Online payment** through Paystack (card and mobile money) when HOLIDO sets its key; every payment is
  confirmed with Paystack before it counts. **Bank transfers and mobile money** are recorded by HOLIDO staff.
- **Renewals and plan changes**: paying extends the subscription; a new plan starts with the next period
  (straight away during a trial); a plan too small for current use is refused; subscriptions can be
  cancelled at the end of the period.
- **Unpaid subscriptions** get a warning banner, then after the grace period the workspace becomes
  read-only — everything can still be read and exported — until the invoice is paid.
- **Billing page** for organizations: plan, usage meters, invoices, paying, changing plan, cancelling.
- **HOLIDO billing console**: invoices, totals, subscriptions needing attention, recording payments,
  cancelling invoices, issuing early, settings, and a "run billing now" button.
- The hourly Render job now also runs `oims billing-run`. New optional setting `PAYSTACK_SECRET_KEY`.
- **Fix:** free plans (price 0) can now be saved on the plan form; before, "0" was rejected as missing.
- Migration `0007`; run `oims sync-roles` (done automatically on Render) for the new billing permissions.

## 0.7.0-phase7 — 15 November 2026

Reporting and analytics.

- **Reports centre** (new "Reports" item in the menu) with ten standard reports: portfolio summary,
  indicator performance, budget and spending, donor funding, activities, beneficiaries reached, feedback and
  complaints, procurement, assets, and staff and leave.
- **Filters** for the period, a programme or project (with or without its projects) and, for staff, the
  department.
- **Charts** with tooltips on hover and keyboard focus, and the full table under each chart.
- **Downloads** as Excel, CSV or PDF; every download is recorded in the audit log.
- Reports show only what each person may see, never count a person or an amount twice, and only count
  sensitive feedback without showing it.
- **Security fix:** text that looks like a spreadsheet formula (for example a title starting with "=") is
  now neutralised in every Excel and CSV export, including the programme reports, beneficiary list, asset
  register and form answers.
- No database changes.

## 0.6.0-phase6 — 15 November 2026

Finance, procurement and assets.

- **Finance overview** across programmes and projects: budget, spent, committed and available; what is
  waiting for your approval; goods received but not yet paid.
- **Purchase requests** charged to a budget line, approved by someone other than the requester only when
  the money is available.
- **Buying rules** set per organization: one quotation, three quotations or a tender, and a written reason
  when the lowest offer is not chosen.
- **Purchase orders** approved by finance commit the money; cancelling releases it.
- **Goods received**, in parts or in full; items marked as assets are added to the asset register.
- **Payments** cannot exceed what was received, are approved by a second person, and release the
  matching commitment; the order closes when everything is received and paid.
- **Suppliers** with encrypted bank details, suspension or blacklisting with a reason, and ratings.
- **Asset register** with custody, transfers, maintenance, yearly checks, depreciation, disposal approval
  and Excel export. Every staff member can see the assets in their care.
- **Project closure** now also checks for open purchase orders and assets still charged to the project.
- New role: **Logistics & Assets Officer**. The Procurement Officer role handles quotations, orders and
  receipts but does not approve requests (budget holders do), keeping buying and approving apart.
- Migration `0006`; run `oims sync-roles` (done automatically on Render).

## 0.5.0-phase5 — 15 November 2026

MEAL & beneficiaries.

- **Beneficiary register**: each person registered once with sex, age or age group, disability, place and
  household; enrolled in any number of programmes and projects.
- **Privacy built in**: phone and ID numbers are encrypted; personal details need their own permission and
  every view is logged; exports are logged; people who leave or withdraw consent can be anonymized.
- **Consent** is recorded at registration (from a parent or guardian for children) and can be withdrawn;
  without it nothing new can be recorded about the person.
- **Duplicate warnings** before registering, and **merging** of duplicate records.
- **Services** received and **named attendance** at activity sessions.
- **People reached** — each person counted once, including across a programme and its projects — on a new
  Beneficiaries tab and in programme and project reports.
- **Data collection**: build forms, publish them, fill them in, have answers checked by a second person,
  see summaries and export to Excel.
- **Feedback & complaints**: from any channel, with reply deadlines, assignment, responses, closure with a
  satisfaction check and reminders. Safeguarding, fraud and misconduct reports are confidential.
- **Public feedback page** that communities can use without an account, anonymously if they wish
  (switched off until an administrator turns it on).
- **MEAL overview** dashboard and a new **Safeguarding Focal Point** role.
- Field Officers can now view monitoring information for their own programmes and projects.
- New status labels ("Inactive", "Exited", "New", "Acknowledged", "Responded", "Published") have colours.
- Migration `0005` adds the new tables; run `oims sync-roles` (done automatically on Render) so existing
  organizations get the new permissions and role.

## 0.4.0-phase4 — 15 November 2026

Project management.

- **Projects** are a separate module with their own menu, list, codes (`PRJ/2026/001`) and permissions.
  A project can stand alone or belong to a programme.
- **Work breakdown**: components, activities, tasks and subtasks on one page, with the deliverables
  each produces. Activities can be placed in a component.
- **Deliverables** with acceptance criteria and due dates. The responsible person submits; someone else
  accepts it or returns it with a note.
- **Risks and issues** for projects and programmes: likelihood × impact rating, a risk matrix, owners and
  review dates, an issue register, and corrective actions assigned as tasks.
- **Closure**: a checklist worked out from the records, a closure report, approval by someone other than
  the manager, and then a read-only archive. Projects can no longer be set to "closed" directly.
- **Programme roll-up**: the programme overview and reports list linked projects with combined budget and
  spending; project indicators can count toward a programme indicator. Nothing is counted twice.
- Project tasks, deliverable deadlines and risk reviews appear in Tasks, the calendar, the dashboard and
  reminders. Tasks show their project, activity, parent task or the issue they correct.
- **Fix:** closed or cancelled programmes are now fully read-only. Before this, managers could still change
  the team or approve and reopen workplans on an archived programme.
- **Fix:** "Planned", "Completed" and "Postponed" status labels now have colours.
- Migration `0004` adds the new tables and `project_id` columns; run `oims sync-roles` (done
  automatically on Render) so existing organizations get the project permissions.

## 0.3.0-phase3 — 15 November 2026

Programmes management.

- **Register programmes** with all the details donors ask for, a manager, a team and a lead department,
  and move them through draft, planned, approved, active, completed and closed.
- **Plan**: strategy, implementation plan, theory of change, assumptions and risks; annual, quarterly and
  monthly workplans with approval; milestones; and a timeline chart of activities and milestones.
- **Results framework**: goal, objectives, outcomes and outputs, with indicators, baselines, period targets,
  means of verification and breakdown by sex, age and disability.
- **Report and verify results**: field staff report results; a different person verifies them before they
  count. The same period and place cannot be counted twice.
- **Activities**: responsible person, location, budget, progress and activity reports with participants,
  challenges and recommendations; photos and attendance sheets as attachments.
- **Finance**: budget lines by category, funding agreements and money received, expenditure and
  commitments approved by a second person, budget revisions, and budget-versus-actual by line and category.
- **Monitoring and learning**: monitoring visits, evaluations, lessons learned and recommendations with
  management responses.
- **Reports**: monthly, quarterly, semi-annual, annual, donor and performance reports that combine your
  narrative with the figures; approved reports are frozen; PDF and Excel export, plus a one-click status
  report for any period.
- **Registers** for donors, locations and budget categories.
- Programme activities and milestones appear in the calendar, on the dashboard and in reminders.
- Migration `0003` adds the new tables only; run `oims sync-roles` (done automatically on Render) so
  existing organizations get the new permissions and starter budget categories.

## 0.2.0-phase2 — 15 November 2026

Office information management.

**New modules**
- **Departments** with heads, responsibilities and per-department staff, tasks and meetings.
- **Staff & HR**: staff register and directory, employment details, emergency contacts, training,
  performance reviews, transfers, exits, and a private staff file for contracts and certificates.
- **Leave**: leave types with yearly entitlements, requests counted in working days, balance and
  overlap checks, approval by the department head or HR, and a list of who is away.
- **Attendance** register by day and department.
- **Documents**: folders, categories, versions, approval, sharing, expiry reminders, archive and
  download history. Files are checked by their content and stored on a persistent disk or in
  S3-compatible storage. Storage limits from the subscription plan apply.
- **Correspondence** register with automatic reference numbers, assignment, forwarding, approval,
  reply deadlines, confidential items and a full routing history.
- **Meetings** with invitations, responses, agenda, attendance, minutes, decisions, action points and
  a printable report.
- **Tasks** with priorities, deadlines, status, comments and attachments.
- **Notifications**, **announcements**, private **messages** and a **calendar**.
- A new dashboard with staff, departments, my tasks, meetings, deadlines, correspondence, documents,
  announcements, notifications and items waiting for approval.

**Security**
- Two-step sign-in with an authenticator app and recovery codes; required for HOLIDO staff.
  Administrators can reset it for someone who has lost their phone.
- "Own department" and "own records" permission scopes now take effect.
- HOLIDO support access stays read-only on every new module and cannot see private messages or HR records.

**Operations**
- Hourly reminders job; `render.yaml` adds it and a persistent disk for documents.
- Database migration `0002` upgrades a Phase 1 database in place (tested with existing data, and
  downgradable).

## 0.1.0-phase1 — 15 November 2026

First release: the foundation every later module builds on.

**For HOLIDO**
- One-time, token-protected setup to create the first Super Admin (or a command-line alternative).
- Platform console with live figures: organizations by status, registrations awaiting approval,
  subscriptions ending soon, sign-ins and failed sign-ins in the last 24 hours, recent activity.
- Approve, reject, suspend, reactivate or deactivate organizations, with reasons kept in the audit log.
- Create organizations directly and invite their administrator.
- Subscription plans with prices, trials and user/storage limits; assign a plan to each organization.
- Manage the HOLIDO team: Super Admins, Platform Administrators and Support Officers.
- Request read-only, time-limited support access to an organization's workspace.

**For organizations**
- Public registration form, reviewed by HOLIDO before the workspace opens.
- Each organization has its own private workspace; no organization can see another's data.
- Fifteen ready-made roles (Executive Director, Programme Director, MEAL Officer, Finance Officer…)
  plus custom roles, with permissions by module, action and scope.
- Add colleagues, change their roles, suspend or remove them; the last administrator is protected.
- Organization profile with logo, contacts, currency, fiscal year and time zone.
- Approve, deny or revoke HOLIDO support access, and see every page support staff viewed.
- Audit log of sign-ins and administrative changes.

**Security**
- Strong password rules, temporary lock after repeated failed sign-ins, limits on sign-in attempts,
  protection against forged form submissions, strict browser security policy, secure cookies,
  sign-out of other devices after a password change, single-use reset links.

**Interface**
- Floating glass design, dark and light modes on every page, phone layout with a slide-in menu and
  bottom navigation bar, collapsible sidebar on computers, confirmation before risky actions.
