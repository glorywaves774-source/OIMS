# ZENTAVA OIMS help guide

<!-- Each section: "## Title", then optional lines
     keywords: words people may use
     links: Label = endpoint [permission]; ...   (shown only if the person may open it)
     who: which roles usually do this
   then the answer text. The assistant answers only from these sections. -->

## Getting around
keywords: menu, navigate, find page, where is, sidebar, phone, tab bar, dark mode, light mode, language, french
links: Dashboard = workspace.dashboard [dashboard.view]; My profile = account.profile
who: everyone
Use the menu on the left (on a phone: the ☰ button at the top left, or the tab bar at the bottom). "Find a page" at the top of the menu filters the pages by name. The moon/sun button switches between dark and light mode, and the EN / FR button switches the language. Your choices are remembered.

## Sign-in, password and two-step sign-in
keywords: password, forgot, reset, login, sign in, locked, two-step, 2fa, authenticator, recovery code, phone lost
links: Change password = account.change_password; Two-step sign-in = account.two_factor
who: everyone; an organization administrator can reset another person's two-step sign-in
To change your password, open Change password. If you forgot it, use "Forgot your password?" on the sign-in page; a link is emailed to you. After several wrong attempts the account is locked for a short time. Two-step sign-in asks for a 6-digit code from an authenticator app; keep your recovery codes safe. If you lost your phone, sign in with a recovery code, or ask your organization administrator to reset two-step sign-in after checking it is really you.

## Tasks
keywords: task, to do, todo, assign, deadline, due date, overdue, subtask, reminder
links: Tasks = tasks.index [tasks.view]; New task = tasks.new [tasks.create]
who: anyone can create tasks; editing anyone's task needs the "manage tasks" permission
Open Tasks to see the tasks assigned to you, the ones you created, or everything you may see. "New task" creates one: give it a title, a due date, a priority and the person responsible. The person is notified, and reminded before the due date. Overdue tasks are marked in red on the dashboard.

## Meetings and minutes
keywords: meeting, minutes, agenda, invite, attendance, decisions, action points
links: Meetings = meetings.index [meetings.view]; Calendar = comms.calendar [calendar.view]
who: people with "schedule meetings"; minutes by the organizer or people who manage meetings
Open Meetings and choose "Schedule a meeting". Participants get an invitation. After the meeting, record the minutes, decisions and action points; action points become tasks for the person responsible. Meetings also appear on the calendar.


## Video calls
keywords: video, call, video call, online meeting, jitsi, zoom, google meet, teams, camera, microphone, join, conference
links: Meetings = meetings.index [meetings.view]
who: anyone invited to the meeting can join; the organizer chooses video when scheduling
When you schedule a meeting, keep "Video call in ZENTAVA OIMS" ticked. Everyone invited then sees "Join video call" on the meeting page. Allow the camera and microphone when the browser asks. With the free setup the call opens in its own tab (Jitsi Meet); keep the meeting page open to take notes. You can instead paste a Google Meet, Zoom or Teams link: the page shows "Join on Zoom" (or the service's name). On a phone, calls work in the browser; the Jitsi Meet app also works.

## Automatic notes and draft minutes
keywords: notes, automatic notes, transcript, transcribe, speech to text, dictate, draft minutes, notes maker, listen
links: Meetings = meetings.index [meetings.view]
who: the organizer or people who manage meetings
Open the meeting (or its video call page) and find "Live notes". Tell everyone the meeting is being written down and tick the box, choose the language spoken, then press "Start listening". What is said appears as text; you can type and correct it. Press "Draft the minutes": the system writes a summary, the decisions, the action points and open questions. Check it, press "Put in the minutes", correct anything, then save. Listening works in Chrome, Edge and Safari and only hears this device's microphone; in an online call use the speaker, not earphones. Then add the formal decisions and action points so they become tasks.
## Leave
keywords: leave, holiday, vacation, sick, annual leave, days off, absence, approve leave, balance
links: Leave = leave.index [leave.request]; Request leave = leave.request_leave [leave.request]; Leave types = leave.types [leave.manage]
who: everyone requests their own leave; heads of department or HR approve it
Choose "Request leave", pick the type and the dates; working days (Monday to Friday) are counted automatically and your approver is notified. You see your balance for the year on the Leave page. Approvers find requests waiting for them on the same page. HR sets the leave types and yearly days.

## Documents
keywords: document, file, upload, folder, version, share, approve document, download, pdf, word
links: Documents = documents.index [documents.view]; Upload a document = documents.upload [documents.upload]; Folders & categories = documents.organize [documents.manage]
who: people with "upload documents"; records officers manage folders and categories
Open Documents and choose "Upload a document". Choose who can see it (everyone, your department, or only people you choose). Uploading a new version keeps the history. Some categories need approval before others can see the document. Allowed files: PDF, Word, Excel, PowerPoint, OpenDocument, CSV, text and images.

## Correspondence (letters and memos)
keywords: letter, correspondence, memo, incoming, outgoing, reference number, reply, register letter
links: Correspondence = correspondence.index [correspondence.view]; Register correspondence = correspondence.new [correspondence.create]
who: records officers register letters; the person a letter is assigned to replies
Register incoming and outgoing letters and internal memos; each gets a reference number such as IN/2026/0001. Assign a letter to someone with a reply date; they are reminded. The routing history shows who handled it.

## Messages, notifications and announcements
keywords: message, chat, notification, announcement, news, unread, bell
links: Messages = comms.inbox [messages.use]; Notifications = comms.notifications; Announcements = comms.announcements [announcements.view]
who: everyone; publishing announcements needs "publish announcements"
Messages are private conversations with colleagues. The bell shows notifications (assignments, approvals, reminders). Announcements are news for the whole organization or a department.

## Staff and HR
keywords: staff, employee, hr, contract, staff record, register staff, exit, transfer, training, performance, directory
links: Staff directory = staff.index [staff.view]
who: HR officers register and maintain staff records
HR registers staff with their employment details, contracts and documents, training, performance reviews and transfers. Staff records are visible only to people allowed to see HR records. When someone leaves, HR records the exit and the record becomes read-only.


## Staff photos
keywords: photo, picture, profile picture, camera, selfie, avatar, staff photo, take photo
links: Staff directory = staff.index [staff.view]
who: HR can set anyone's photo; each person can set their own
Open the staff profile and press "Take photo": allow the camera, face it in good light, press "Take photo", then "Use photo". On a phone you can switch to the back camera to photograph a colleague. "Upload photo" lets you choose a picture instead. The photo is cropped to a square and shown in the staff directory, only to colleagues in your organization.
## Attendance
keywords: attendance, present, absent, register, daily attendance
links: Attendance = attendance.register [attendance.record]
who: people with "record attendance" (often heads of department)
Open Attendance, tick who is present, absent or on leave for the day, and save.

## Departments, users and roles
keywords: department, user, invite, role, permission, access, admin, add user, remove user, suspend
links: Departments = departments.index [departments.view]; Users = workspace.users [users.view]; Invite a user = workspace.user_invite [users.invite]; Roles = workspace.roles [roles.view]
who: organization administrators
Administrators invite users and give each one role. Standard roles are kept up to date; to change one, duplicate it as a custom role. Each permission can be limited to the whole organization, the person's department, or their own records.

## Organization settings
keywords: settings, logo, organization profile, currency, time zone, fiscal year, workspace settings
links: Settings = workspace.settings [organization.view]
who: organization administrators
Settings holds the organization's profile, logo, main currency, time zone, fiscal year and office lists.

## Programmes
keywords: programme, program, register programme, results framework, logframe, indicators, workplan, activities, milestones, donor, budget
links: Programmes = programmes.index [programmes.view]; Register a programme = programmes.new [programmes.create]
who: programme directors and managers
Register a programme with its goal, dates, manager and approved budget. Then build the results framework (goal, objectives, outcomes, outputs) with indicators, the workplans and activities, milestones and budget lines. A programme is approved before money is spent; after that, budget changes go through a budget revision.

## Projects
keywords: project, work breakdown, wbs, deliverable, risk, issue, closure, close project, component
links: Projects = projects.index [projects.view]; Register a project = projects.new [projects.create]
who: project managers
A project can be part of a programme or independent. Plan it with components, activities, tasks and deliverables, keep the risk and issue registers, and close it with the closure checklist and approval.

## Budget, expenditure and approvals
keywords: budget, expenditure, spend, payment, commitment, approve expenditure, budget line, budget revision, finance
links: Finance overview = finance.overview [finance.view]
who: finance officers record and approve; another person must approve what someone recorded
Spending is recorded against a budget line of a programme or project and counts only when another person with approval rights approves it. Commitments reserve money for orders and contracts. The finance overview shows budgets, spending and what waits for your approval.

## Exchange rates
keywords: exchange rate, currency, convert, dollar, euro, cedi, combined total
links: Exchange rates = finance.rates [finance.view]
who: finance officers (permission "set exchange rates")
Under Finance → Exchange rates the finance team records dated rates (for example 1 USD = 15.40 GHS from 1 November). They are used for combined totals in the organization's currency; spending in a report period uses the rate of the day of each payment. A currency without a rate is left out and named.

## Purchases (procurement)
keywords: purchase, buy, procurement, purchase request, quotation, purchase order, supplier, goods received, tender
links: Procurement = procurement.index [procurement.view]; New purchase request = procurement.new [procurement.request]; Suppliers = procurement.suppliers [procurement.view]
who: anyone with "raise purchase requests"; approval by a manager; the procurement office handles quotations and orders
Raise a purchase request against a budget line. After approval, the procurement office records quotations (one, three, or a tender depending on the amount), prepares the purchase order, and records goods received. Payment is possible for what has been received.

## Assets
keywords: asset, equipment, laptop, vehicle, motorbike, tag, assign asset, disposal, inventory, register asset
links: Asset register = assets.index [assets.view]; Register an asset = assets.edit [assets.manage]
who: logistics and assets officers; disposals are approved by someone else
Items bought as assets are added to the register automatically. Each asset has a tag, a custodian, a location and checks. Request a disposal when an asset is lost, broken or given away; another person approves it.

## Beneficiaries
keywords: beneficiary, register beneficiary, enrol, consent, household, service, attendance, duplicate, anonymize
links: Beneficiaries = beneficiaries.index [beneficiaries.view]; Register a beneficiary = beneficiaries.new [beneficiaries.register]; Households = beneficiaries.households [beneficiaries.view]
who: field officers and MEAL officers register; personal details only for people allowed to see them
Register a person once (the system warns about likely duplicates), record their consent, then enrol them in a programme or project and record services and attendance. Without current consent nothing new can be recorded. Phone and ID numbers are stored encrypted.

## MEAL, indicators and data collection
keywords: meal, monitoring, evaluation, indicator, result, verify, data collection, form, survey, answers
links: MEAL overview = meal.dashboard [meal.view]; Data-collection forms = meal.forms [meal.view]
who: MEAL officers define indicators and verify; field staff report and collect
Report indicator results; they count only after someone other than the reporter verifies them. Data-collection forms are surveys and checklists your team fills in; answers are checked by a second person.

## Feedback and complaints
keywords: feedback, complaint, suggestion, safeguarding, community, hotline, public feedback page
links: Feedback = feedback.index [feedback.view]; Record feedback = feedback.new [feedback.record]; Public feedback page = feedback.settings [feedback.manage]
who: anyone with "record feedback"; sensitive cases only for safeguarding staff
Record feedback received from communities, assign it, respond and close it with the person's satisfaction. Reports of abuse, fraud or misconduct are confidential and go only to safeguarding staff. A public page lets people send feedback without an account.

## Reports and exports
keywords: report, export, excel, csv, pdf, donor report, chart, analytics, download
links: Reports = analytics.index [reports.view]
who: people with "view reports"
Reports cover the portfolio, indicators, budget and spending, donors, activities, beneficiaries, feedback, procurement, assets and staff, for any period, and download as Excel, CSV or PDF. Each shows only what you may see. Programme and project narrative reports are written on their Reports tab and approved.

## Subscription and billing
keywords: subscription, plan, invoice, pay, billing, payment, overdue, read-only, upgrade
links: Billing = billing.index [billing.view]
who: organization administrators
The Billing page shows the plan, usage and invoices. Pay online or by bank transfer using the invoice number as the reference. If an invoice stays unpaid after the grace period, the workspace becomes read-only until it is paid; nothing is deleted.

## Support access by Kayron
keywords: support, kayron, help desk, access request, support access
links: Support access = workspace.support [support.view]
who: organization administrators approve
Kayron staff can only view your workspace (never change it), for a limited time, after you approve, and every page they open is recorded in your audit log.

## Kayron platform console
keywords: platform, tenant, organizations, approve organization, plans, platform staff, platform billing
links: Platform dashboard = platform.dashboard [platform]; Organizations = platform.organizations [platform]; Subscription plans = platform.plans [platform]; Billing = platform_billing.index [platform]
who: Kayron platform staff only
The console lists organizations (approve, suspend, create), subscription plans, platform staff, billing and the platform audit log.
