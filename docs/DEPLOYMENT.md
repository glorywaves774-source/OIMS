# Deploying and maintaining OIMS

## Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `OIMS_ENV` | yes | `production` on servers (`development` locally) |
| `SECRET_KEY` | yes | ≥ 32 random characters; signs sessions and reset links. Changing it signs everyone out. |
| `DATABASE_URL` | yes | PostgreSQL URL (`postgres://` and `postgresql://` both accepted) |
| `PUBLIC_BASE_URL` | recommended | e.g. `https://oims.holido.org`; used in emailed links |
| `SESSION_COOKIE_SECURE` | — | `true` (default) in production — requires HTTPS |
| `SESSION_HOURS` | — | Session lifetime, default 8 |
| `OIMS_SETUP_TOKEN` | first run only | Enables the one-time `/setup` page. Remove after use. |
| `OIMS_SUPERADMIN_EMAIL` / `_NAME` / `_PASSWORD` | first run only | For the CLI setup method. Remove after use. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM` | recommended | Outgoing email for invitations and password resets |
| `RATELIMIT_STORAGE_URI` | multi-instance | `redis://…` when running more than one instance (default is per-process memory) |
| `LOGIN_MAX_FAILURES`, `LOGIN_LOCKOUT_MINUTES`, `PASSWORD_MIN_LENGTH` | — | Security tuning (defaults 5, 15, 12) |
| `ALLOW_PUBLIC_REGISTRATION` | — | `false` to hide the public registration form |
| `TRUST_PROXY` | — | `1` (default) behind Render's proxy; `0` if exposed directly |
| `LOG_LEVEL` | — | `INFO` by default |

Without SMTP, invitation and set-password links are shown **once** to the administrator who created
the account, and password-reset requests are written to the server log only. Configure SMTP before
inviting real users.

## Render (from GitHub)

1. Push this repository to GitHub.
2. In Render choose **New → Blueprint** and select the repository; Render reads `render.yaml`
   (web service + PostgreSQL). Check the plan names in `render.yaml` against Render's current offer.
3. Fill in the variables marked `sync: false` (`PUBLIC_BASE_URL`, SMTP settings, and for the first
   deploy `OIMS_SETUP_TOKEN` — a long random value).
4. Deploy. `preDeployCommand` runs `flask --app wsgi db upgrade` before each release.
5. Open `https://<your-service>/setup`, enter the token and create the HOLIDO Super Admin.
6. **Delete `OIMS_SETUP_TOKEN`** from Render. The page also locks itself once a Super Admin exists.
7. Health check: `GET /healthz` returns `{"status": "ok", "database": "ok"}`.

Alternative first-run method: open a Render Shell and run
`OIMS_SUPERADMIN_EMAIL=… OIMS_SUPERADMIN_PASSWORD=… flask --app wsgi oims create-superadmin`.

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

- Test a restore at least once per quarter. Organization logos are stored in the database in
  Phase 1, so a database backup is complete. From Phase 2, uploaded documents go to object storage,
  which needs its own backup/versioning policy.

## Logging and monitoring

- Application and access logs go to standard output (visible in Render's log stream).
- Security events (sign-ins, failures, lockouts, support access, administrative changes) are in the
  audit log, visible to HOLIDO at **Platform → Audit log** and to each organization in its workspace.
- Point an uptime monitor at `/healthz`. Error-tracking services (e.g. Sentry) can be added through
  an environment variable in a later phase; none is integrated yet.

## Routine maintenance

- Rotate `SECRET_KEY` only when necessary (it signs everyone out).
- Review platform staff accounts and the audit log monthly.
- Keep dependencies updated (`pip list --outdated`), run `pytest`, then deploy.
