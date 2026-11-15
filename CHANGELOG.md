# Changelog

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
