# Deploying and maintaining ZENTAVA

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OIMS_ENV` | yes | `production` on servers (`development` locally) |
| `SECRET_KEY` | yes | ≥ 32 random characters; signs sessions and reset links and encrypts two-step sign-in keys. Changing it signs everyone out, **disables everyone's two-step sign-in** and **makes encrypted beneficiary phone and ID numbers and feedback contacts unreadable**. Keep it stable and backed up. |
| `DATABASE_URL` | yes | PostgreSQL URL (`postgres://` and `postgresql://` both accepted) |
| `PUBLIC_BASE_URL` | yes | e.g. `https://app.zentava.com`; used in emailed links (must start with `https://`) |
| `SESSION_COOKIE_SECURE` | — | `true` (default) in production — requires HTTPS |
| `SESSION_HOURS` | — | Session lifetime, default 8 |
| `OIMS_SETUP_TOKEN` | first run only | Enables the one-time `/setup` page. Remove after use. |
| `OIMS_SUPERADMIN_EMAIL` / `_NAME` / `_PASSWORD` | first run only | For the CLI setup method. Remove after use. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM` | recommended | Outgoing email for invitations and password resets |
| `STORAGE_BACKEND` | yes | `local` (files on a persistent disk) or `s3` (S3-compatible object storage) |
| `UPLOAD_ROOT` | with `local` | Absolute path on a persistent disk, e.g. `/var/data/uploads` |
| `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_PREFIX` | with `s3` | Object storage. Leave `S3_ENDPOINT_URL` blank for AWS; set it for Cloudflare R2, Backblaze B2, DigitalOcean Spaces or MinIO. |
| `S3_SERVER_SIDE_ENCRYPTION` | — | `true` (default) asks the store to encrypt files at rest; set `false` if your provider rejects it |
| `MAX_UPLOAD_MB` | — | Largest file accepted, default 25 |
| `REQUIRE_PLATFORM_2FA` | — | `true` (default in production): Kayron staff must use two-step sign-in |
| `RATELIMIT_STORAGE_URI` | multi-instance | `redis://…` when running more than one instance (default is per-process memory) |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`, `PASSWORD_MIN_LENGTH` | — | Security tuning (defaults 5, 15, 12) |
| `ALLOW_PUBLIC_REGISTRATION` | — | `false` to hide the public registration form |
| `TRUST_PROXY` | — | `1` (default) behind Render's proxy; `0` if exposed directly |
| `LOG_LEVEL` | — | `INFO` by default |
| `PAYSTACK_SECRET_KEY` | — | Turns on online subscription payments (card and mobile money) through Paystack. Leave empty to accept bank transfers recorded by Kayron staff only |
| `PAYSTACK_API_BASE` | — | Defaults to `https://api.paystack.co` (must be `https://`) |
| `BACKUP_ENCRYPTION_KEY` | yes (backup job) | Encrypts backups. Create with `flask --app wsgi oims backup-key`. **Keep a copy in a password manager**: without it no backup can be restored. |
| `BACKUP_S3_BUCKET`, `BACKUP_S3_ENDPOINT_URL`, `BACKUP_S3_REGION`, `BACKUP_S3_ACCESS_KEY_ID`, `BACKUP_S3_SECRET_ACCESS_KEY`, `BACKUP_S3_PREFIX` | yes (backup job) | Where backups go: a bucket **separate** from documents, ideally with another provider (e.g. Backblaze B2 or Cloudflare R2) |
| `BACKUP_DIR` | — | Alternative to a bucket: a folder (self-hosting, tests) |
| `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_MONTHLY` | — | Backups kept: last 14 days plus one per month for 12 months (defaults) |
| `WEB_CONCURRENCY`, `GUNICORN_THREADS` | — | Web server processes and threads (defaults 1 and 4, for the 512 MB plan); see *Capacity* |
| `MALLOC_ARENA_MAX` | — | `2` (set in `render.yaml`) keeps memory use of the threaded server low |
| `HELP_AI_API_KEY` (or `ANTHROPIC_API_KEY`) | — | Lets the help assistant phrase its answers with an AI service (Anthropic). Without it, the assistant answers straight from the help guide. |
| `HELP_AI_MODEL` | — | AI model for the assistant, default `claude-haiku-5-5` |
| `HELP_ASSISTANT` | — | `false` hides the help assistant |
| `HEAVY_DOWNLOADS`, `HEAVY_DOWNLOAD_WAIT` | — | Large exports prepared at the same time per process (default 1) and seconds to wait for a turn (default 20) |

Without SMTP, invitation and set-password links are shown **once** to the administrator who created
the account, and password-reset requests are written to the server log only. Configure SMTP before
inviting real users.

## Render (from GitHub)

1. Push this repository to GitHub.
2. In Render choose **New → Blueprint** and select the repository; Render reads `render.yaml`
   (web service with a 10 GB persistent disk for documents, an hourly reminders job, a nightly backup job,
   and PostgreSQL).
   Check the plan names in `render.yaml` against Render's current offer.
3. Fill in the variables marked `sync: false` (`PUBLIC_BASE_URL`, SMTP settings, the backup settings and
   for the first deploy `OIMS_SETUP_TOKEN` — a long random value).
4. Deploy. `preDeployCommand` runs the database migrations and `oims sync-roles` before each release.
5. Open `https://<your-service>/setup`, enter the token and create the Kayron Super Admin.
   You are then asked to set up two-step sign-in with an authenticator app — **save the recovery codes**.
6. **Delete `OIMS_SETUP_TOKEN`** from Render. The page also locks itself once a Super Admin exists.
7. Health check: `GET /healthz` returns `{"status": "ok", "database": "ok"}`.

Alternative first-run method: open a Render Shell and run
`OIMS_SUPERADMIN_EMAIL=… OIMS_SUPERADMIN_PASSWORD=… flask --app wsgi oims create-superadmin`.

## Document storage

Uploaded files are stored under random names (`org-<id>/<random>`) and are only ever served through
ZENTAVA after a permission check. Every upload is checked by its content, not just its name: PDF, Word,
Excel, PowerPoint, OpenDocument, CSV, text and common images are accepted; anything else is refused.

- **Persistent disk (default in `render.yaml`)** — simplest. Files survive deploys. A Render disk
  attaches to a single instance, so you cannot scale the web service to several instances, and
  deploys have a few seconds of downtime. Back up the disk (see below).
- **S3-compatible object storage** — set `STORAGE_BACKEND=s3` and the `S3_*` variables, and remove
  the `disk` block from `render.yaml`. Recommended once you need more than one web instance. Turn on
  bucket versioning so deleted or overwritten files can be recovered. Keep the bucket private.

Changing backend later requires copying the existing files across (keys stay the same).

## Scheduled reminders

`flask --app wsgi oims send-reminders` creates in-app notifications (and emails, if SMTP is set) for
tasks due today/tomorrow and overdue tasks, meetings in the next 24 hours, documents expiring within
30 days and correspondence replies due within 2 days. Each reminder is sent once per item and person,
so running it more often never repeats a reminder. `render.yaml` runs it hourly as a Cron Job;
on other hosts use any scheduler (cron, systemd timer).

## Subscription billing

`flask --app wsgi oims billing-run` issues invoices before each period (or trial) ends, marks unpaid
subscriptions past due when the period ends, makes a workspace read-only after the grace period, and
sends payment reminders. It is safe to run hourly (nothing is issued or sent twice); `render.yaml` runs it
right after the reminders. Kayron super administrators set the invoice details, bank instructions, tax,
lead time and grace period under **Platform → Billing → Settings**.

Online payments (optional):
1. Create a Paystack account for Kayron and copy the **secret key** into `PAYSTACK_SECRET_KEY` (Render
   dashboard → Environment). Use the test key first.
2. In Paystack → Settings → API keys & webhooks, set the webhook URL to
   `https://<your domain>/billing-webhooks/paystack` (the settings page shows the exact address).
3. Make a test payment from an organization's Billing page. Every payment is confirmed by asking
   Paystack directly before it is recorded; webhooks are checked with Paystack's signature.

A subscription without a period end (and without a trial end) is a manual arrangement and is never
invoiced automatically — set a period end on the organization's page to start automatic billing.

## Two-step sign-in

- Kayron platform staff must use an authenticator app (`REQUIRE_PLATFORM_2FA=true`). Organization
  users may turn it on from **My account → Two-step sign-in**.
- Each person gets 10 single-use recovery codes. If someone loses both their phone and their codes,
  confirm their identity first, then: a **Super Admin** resets Kayron staff from **Platform staff**; an
  **organization administrator** resets their own members from **Users → (person)**. The person is
  signed out and sets it up again at next sign-in. Both actions are recorded in the audit log.

## Database migrations

```bash
flask --app wsgi db upgrade                      # apply
flask --app wsgi db migrate -m "describe change" # after changing models (review the file!)
flask --app wsgi db check                        # confirm models and migrations agree
flask --app wsgi oims sync-roles                 # after adding permissions in a new phase
```

## Backups and recovery

Three layers protect the data:

| Layer | What | Kept | Set up |
|---|---|---|---|
| Render Postgres point-in-time recovery | the database, to any moment | 3 days (Hobby workspace) or 7 days (Pro+) on paid databases | automatic |
| Render disk snapshots | uploaded documents on the disk | daily, at least 7 days | automatic |
| **ZENTAVA off-site backups** | the database + every uploaded document, encrypted, at another provider | 14 daily + 12 monthly | the `oims-backup` job below |

The first two are quickest for "undo yesterday's mistake". The third survives problems with the Render
account itself and gives a year of history.

### Setting up the off-site backups

1. Create a bucket at a different provider from Render (e.g. Backblaze B2 or Cloudflare R2) with its own
   access key that can read, write and delete in that bucket only.
2. Create the encryption key once, on any computer with the code: `flask --app wsgi oims backup-key`.
   Store it in your password manager **together with `SECRET_KEY`** (encrypted personal data needs it too).
3. In Render, on the `oims-backup` job, fill in `BACKUP_ENCRYPTION_KEY` and the `BACKUP_S3_*` values.
4. Run the job once (**Trigger run**), then check with `flask --app wsgi oims backup-list` and
   `flask --app wsgi oims check-deploy`.

What each nightly run does: one consistent snapshot of every table (taken while people keep working),
encrypted and uploaded; uploaded documents that are not in the backup yet are added (each is copied once:
documents never change, a new version is a new file); older backups beyond the retention are removed.
Documents on the web service's disk cannot be read by a separate job, so with `STORAGE_BACKEND=local` the
job backs up the database only and the disk is covered by Render's daily snapshots. **For off-site copies of
documents use `STORAGE_BACKEND=s3`** (recommended for go-live); then the job copies them too.

### Restoring

Restore always goes into a **new, empty database**, never over the live one:

1. Create a new Render Postgres database (or use point-in-time recovery, which also creates a new one).
2. From a Render Shell (or any computer with the code), point `DATABASE_URL` at the new database, set the
   backup variables, and run:

   ```bash
   flask --app wsgi oims backup-list                       # choose a backup
   flask --app wsgi oims backup-verify zentava-YYYYMMDD-HHMMSS.ztvbak
   flask --app wsgi oims restore zentava-YYYYMMDD-HHMMSS.ztvbak --yes
   ```

   The restore checks every table against its checksum and row count, puts documents back into the
   document storage configured in that shell, then upgrades the database to the current version.
3. Sign in on a copy of the service pointed at the new database and check a few records and documents.
4. Switch the web service, reminders job and backup job to the new database and redeploy.

**Practise this once before go-live and then every quarter** (on the free test database, not the live one).
It was rehearsed during Phase 9 on a large test database: 240,251 rows backed up in 3 seconds and
restored in 25 seconds, with all 89 tables identical afterwards.

## Logging and monitoring

- Application and access logs go to standard output (visible in Render's log stream).
- Security events (sign-ins, failures, lockouts, support access, administrative changes) are in the
  audit log, visible to Kayron at **Platform → Audit log** and to each organization in its workspace.
- Point an uptime monitor (e.g. UptimeRobot, Better Stack) at `https://<your address>/healthz`; it answers
  `{"status": "ok", "database": "ok"}`, or 503 when the database cannot be reached.
- Render can email you when a deploy fails or the service restarts (Render → Notifications).
- No outside error-tracking service is connected, so no personal data leaves the system; errors are in the
  log stream with the time and page.

## Help assistant

The round ✦ button on every signed-in page opens the ZENTAVA Assistant. It answers "how do I…" questions from
the help guide in `app/help/guide.en.md` and `guide.fr.md` (edit these to change what it knows; keep the two in
step — a test checks they have the same sections and links). Links in answers are built by the app and only for
pages the person's role can open. With `HELP_AI_API_KEY` set, the matching guide sections and the question are
sent to Anthropic's API to phrase a short answer: phone numbers, emails and ID numbers are removed from the
question first, and no records, names or organization details are sent. Questions are not stored. Limits: 12 per
minute and 200 per day per person.

## Capacity

Measured in Phase 9 with one organization holding 16,000 beneficiaries, 20,000 enrolments, 18,000 tasks,
14,000 expenditures and 8,000 assets, plus 60 other organizations:

| Server | Comfortable load | Notes |
|---|---|---|
| One processor core, 1 process × 4 threads | about 30 people clicking at the same time (13 pages a second; half of pages under 0.1–0.2 s) | 60 at once: pages wait about 1.5 s |
| Render **starter** (512 MB, half a core) | estimated about 15 people active at the same moment (half the measured core), i.e. organizations with a few hundred staff in total | peak memory measured about 315 MB even with large exports running |

Large exports (spreadsheets of every beneficiary, report PDFs) are prepared one at a time per process; others
get a "try again in a minute" page instead of slowing everyone down. To grow: move to a plan with more
processor and memory and raise `WEB_CONCURRENCY` (about one process per core and 300 MB); with more than one
process set `RATELIMIT_STORAGE_URI` to a Redis/Key Value store, and with more than one *instance* use
`STORAGE_BACKEND=s3` (a disk attaches to one instance only).

## Going live: checklist

1. Deploy from the release branch; let the migrations run.
2. Set `PUBLIC_BASE_URL` (your own address, e.g. `https://app.zentava.com`, added under Render → Custom
   Domains) and SMTP; send yourself a password reset to test email.
3. Create the Super Admin (`/setup`), set up two-step sign-in, save the recovery codes, **remove
   `OIMS_SETUP_TOKEN`**.
4. Platform → Billing → Settings: company name, address, bank/mobile-money instructions, tax. Create the
   subscription plans.
5. Paystack (optional): start with the test key, make one test payment end to end, then switch to the
   live key.
6. Backups: set up as above, run once, **restore it once into a test database**.
7. Run `flask --app wsgi oims check-deploy` in a Render Shell and fix every FAIL.
8. Uptime monitor on `/healthz`; Render notifications on.
9. A quick check on a real iPhone and Android phone (the phone layouts were checked in Chrome's emulation).
10. Register a first organization yourself and walk through: invite a user, a task, a document, a leave
    request, a programme with a budget, an invoice.

## Routine maintenance

- Every month: `flask --app wsgi oims check-deploy`; look at the newest backup date; review platform staff
  accounts and the audit log.
- Every quarter: a restore practice into a test database (above).
- Dependencies are pinned to the exact versions that were tested (`requirements.txt`). To update: change a
  version, run `pip-audit -r requirements.txt` and the tests (`pytest`, also with
  `TEST_DATABASE_URL=postgresql+psycopg://…`), then deploy.
- Do not rotate `SECRET_KEY` casually: it signs everyone out, resets two-step sign-in and makes encrypted personal
  data (beneficiary phones and ID numbers, feedback contacts) unreadable. Store a copy in your password manager.
- The public feedback page (`/f/<organization>`) is limited to 10 messages per hour per address; put the app behind
  Render's proxy as documented so the limit sees real addresses.
