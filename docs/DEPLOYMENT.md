# Deploying and maintaining OIMS

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OIMS_ENV` | yes | `production` on servers (`development` locally) |
| `SECRET_KEY` | yes | ≥ 32 random characters; signs sessions and reset links and encrypts two-step sign-in keys. Changing it signs everyone out, **disables everyone's two-step sign-in** and **makes encrypted beneficiary phone and ID numbers and feedback contacts unreadable**. Keep it stable and backed up. |
| `DATABASE_URL` | yes | PostgreSQL URL (`postgres://` and `postgresql://` both accepted) |
| `PUBLIC_BASE_URL` | recommended | e.g. `https://oims.holido.org`; used in emailed links |
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
| `REQUIRE_PLATFORM_2FA` | — | `true` (default in production): HOLIDO staff must use two-step sign-in |
| `RATELIMIT_STORAGE_URI` | multi-instance | `redis://…` when running more than one instance (default is per-process memory) |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`, `PASSWORD_MIN_LENGTH` | — | Security tuning (defaults 5, 15, 12) |
| `ALLOW_PUBLIC_REGISTRATION` | — | `false` to hide the public registration form |
| `TRUST_PROXY` | — | `1` (default) behind Render's proxy; `0` if exposed directly |
| `LOG_LEVEL` | — | `INFO` by default |
| `PAYSTACK_SECRET_KEY` | — | Turns on online subscription payments (card and mobile money) through Paystack. Leave empty to accept bank transfers recorded by HOLIDO staff only |
| `PAYSTACK_API_BASE` | — | Defaults to `https://api.paystack.co` |

Without SMTP, invitation and set-password links are shown **once** to the administrator who created
the account, and password-reset requests are written to the server log only. Configure SMTP before
inviting real users.

## Render (from GitHub)

1. Push this repository to GitHub.
2. In Render choose **New → Blueprint** and select the repository; Render reads `render.yaml`
   (web service with a 10 GB persistent disk for documents, an hourly reminders job, and PostgreSQL).
   Check the plan names in `render.yaml` against Render's current offer.
3. Fill in the variables marked `sync: false` (`PUBLIC_BASE_URL`, SMTP settings, and for the first
   deploy `OIMS_SETUP_TOKEN` — a long random value).
4. Deploy. `preDeployCommand` runs the database migrations and `oims sync-roles` before each release.
5. Open `https://<your-service>/setup`, enter the token and create the HOLIDO Super Admin.
   You are then asked to set up two-step sign-in with an authenticator app — **save the recovery codes**.
6. **Delete `OIMS_SETUP_TOKEN`** from Render. The page also locks itself once a Super Admin exists.
7. Health check: `GET /healthz` returns `{"status": "ok", "database": "ok"}`.

Alternative first-run method: open a Render Shell and run
`OIMS_SUPERADMIN_EMAIL=… OIMS_SUPERADMIN_PASSWORD=… flask --app wsgi oims create-superadmin`.

## Document storage

Uploaded files are stored under random names (`org-<id>/<random>`) and are only ever served through
OIMS after a permission check. Every upload is checked by its content, not just its name: PDF, Word,
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
right after the reminders. HOLIDO super administrators set the invoice details, bank instructions, tax,
lead time and grace period under **Platform → Billing → Settings**.

Online payments (optional):
1. Create a Paystack account for HOLIDO and copy the **secret key** into `PAYSTACK_SECRET_KEY` (Render
   dashboard → Environment). Use the test key first.
2. In Paystack → Settings → API keys & webhooks, set the webhook URL to
   `https://<your domain>/billing-webhooks/paystack` (the settings page shows the exact address).
3. Make a test payment from an organization's Billing page. Every payment is confirmed by asking
   Paystack directly before it is recorded; webhooks are checked with Paystack's signature.

A subscription without a period end (and without a trial end) is a manual arrangement and is never
invoiced automatically — set a period end on the organization's page to start automatic billing.

## Two-step sign-in

- HOLIDO platform staff must use an authenticator app (`REQUIRE_PLATFORM_2FA=true`). Organization
  users may turn it on from **My account → Two-step sign-in**.
- Each person gets 10 single-use recovery codes. If someone loses both their phone and their codes,
  confirm their identity first, then: a **Super Admin** resets HOLIDO staff from **Platform staff**; an
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

- Enable Render's automated PostgreSQL backups (point-in-time recovery on paid plans).
- Additionally take a periodic logical backup stored outside Render:

  ```bash
  pg_dump --format=custom --no-owner "$DATABASE_URL" > oims-$(date +%F).dump
  ```

- Restore into an empty database:

  ```bash
  pg_restore --no-owner --dbname "$TARGET_DATABASE_URL" oims-YYYY-MM-DD.dump
  ```

- Test a restore at least once per quarter.
- **Documents are not in the database.** Back up the storage as well:
  - persistent disk: Render takes daily disk snapshots; also copy `/var/data/uploads` off-site
    regularly (for example `tar` + upload from a Render Shell, or `rclone` to another bucket);
  - object storage: enable bucket versioning and, ideally, replication to a second bucket.
- Restore the database and the files from the **same point in time**; a document whose file is
  missing returns "410 Gone" on download rather than failing silently.

## Logging and monitoring

- Application and access logs go to standard output (visible in Render's log stream).
- Security events (sign-ins, failures, lockouts, support access, administrative changes) are in the
  audit log, visible to HOLIDO at **Platform → Audit log** and to each organization in its workspace.
- Point an uptime monitor at `/healthz`. Error-tracking services (e.g. Sentry) can be added through
  an environment variable in a later phase; none is integrated yet.

## Routine maintenance

- Do not rotate `SECRET_KEY` casually: it signs everyone out, resets two-step sign-in and makes encrypted personal
  data (beneficiary phones and ID numbers, feedback contacts) unreadable. Store a copy in your password manager.
- The public feedback page (`/f/<organization>`) is limited to 10 messages per hour per address; put the app behind
  Render's proxy as documented so the limit sees real addresses.
- Review platform staff accounts and the audit log monthly.
- Keep dependencies updated (`pip list --outdated`), run `pytest`, then deploy.
