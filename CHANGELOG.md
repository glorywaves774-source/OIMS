# Changelog

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
