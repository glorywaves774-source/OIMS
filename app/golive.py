"""Go-live check: ``flask --app wsgi oims check-deploy``.

Looks at the running configuration and data and reports, in plain words, what is ready (OK), what should be
looked at (WARN) and what must be fixed before people use the system (FAIL). Changes nothing, except a
small test file written to and removed from document storage.
"""
from datetime import datetime, timedelta, timezone

from flask import current_app
from sqlalchemy import select, text

from app.extensions import db

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def run_checks():
    cfg = current_app.config
    out = []

    def add(status, what, detail=""):
        out.append((status, what, detail))

    # --- settings ---
    prod = cfg.get("OIMS_CONFIG_NAME") == "production"
    add(OK if prod else FAIL, "Production settings", "OIMS_ENV=production" if prod
        else f"running with '{cfg.get('OIMS_CONFIG_NAME')}' settings: set OIMS_ENV=production")
    base = cfg.get("PUBLIC_BASE_URL")
    add(OK if base and base.startswith("https://") else FAIL, "Public web address",
        base or "set PUBLIC_BASE_URL (used in email links), e.g. https://app.zentava.com")
    add(OK if cfg.get("REQUIRE_PLATFORM_2FA") else FAIL, "Two-step sign-in required for Kayron staff",
        "" if cfg.get("REQUIRE_PLATFORM_2FA") else "set REQUIRE_PLATFORM_2FA=true")

    # --- database ---
    try:
        db.session.execute(text("select 1"))
        add(OK, "Database reachable")
    except Exception as exc:  # noqa: BLE001 - report any connection problem plainly
        add(FAIL, "Database reachable", str(exc).splitlines()[0])
        return out
    try:
        from alembic.script import ScriptDirectory
        from flask_migrate import Migrate  # noqa: F401 - ensures the extension is configured
        mig = current_app.extensions["migrate"]
        heads = set(ScriptDirectory.from_config(mig.migrate.get_config()).get_heads())
        current = db.session.execute(text("select version_num from alembic_version")).scalar()
        add(OK if current in heads else FAIL, "Database structure up to date",
            current if current in heads else f"at {current}, latest {', '.join(heads)}: run flask db upgrade")
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()   # PostgreSQL refuses further queries in a failed transaction
        add(FAIL, "Database structure up to date", f"could not read the revision: {str(exc).splitlines()[0]}")

    # --- accounts ---
    from app.models import PlatformRole, SubscriptionPlan, User
    from app.tenancy import unscoped
    supers = db.session.execute(unscoped(select(User).where(User.platform_role == PlatformRole.SUPER_ADMIN,
                                                            User.is_enabled.is_(True)))).scalars().all()
    add(OK if supers else FAIL, "Kayron Super Admin exists",
        f"{len(supers)} active" if supers else "create one: /setup or flask oims create-superadmin")
    staff = db.session.execute(unscoped(select(User).where(User.platform_role.isnot(None),
                                                           User.is_enabled.is_(True)))).scalars().all()
    no2fa = [u for u in staff if not u.has_2fa]
    add(OK if not no2fa else WARN, "Kayron staff have set up two-step sign-in",
        f"{len(no2fa)} of {len(staff)} still to do it at their next sign-in" if no2fa else f"all {len(staff)}")
    if cfg.get("SETUP_TOKEN"):
        add(FAIL if supers else WARN, "First-run setup token removed",
            "delete OIMS_SETUP_TOKEN from the environment now" if supers else "remove it after creating the Super Admin")
    else:
        add(OK, "First-run setup token removed")

    # --- documents ---
    try:
        from app.storage import get_storage
        store = get_storage()
        key = f"golive-check/{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
        store.put(key, b"ok", "text/plain")
        good = store.get(key) == b"ok"
        store.delete(key)
        add(OK if good else FAIL, "Document storage works", cfg.get("STORAGE_BACKEND"))
    except Exception as exc:  # noqa: BLE001
        add(FAIL, "Document storage works", str(exc).splitlines()[0])

    # --- email ---
    if cfg.get("SMTP_HOST"):
        frm = cfg.get("MAIL_FROM") or ""
        add(OK if not frm.endswith(".local") else WARN, "Email sending set up",
            cfg["SMTP_HOST"] if not frm.endswith(".local") else "set MAIL_FROM to a real address")
    else:
        add(WARN, "Email sending set up", "no SMTP_HOST: invitations and resets are shown on screen instead")

    # --- backups ---
    try:
        from app.backup import BackupError, _key, get_target, list_backups
        _key()
        names = list_backups(get_target())
        if not names:
            add(WARN, "Backups", "set up, but none made yet: run flask oims backup once and check it")
        else:
            newest = datetime.strptime(names[-1][8:23], "%Y%m%d-%H%M%S").replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - newest
            add(OK if age < timedelta(hours=26) else WARN, "Backups",
                f"{len(names)} kept, newest {names[-1]}" + ("" if age < timedelta(hours=26)
                                                            else f" ({age.days} day(s) old: check the backup job)"))
    except BackupError as exc:
        add(FAIL, "Backups", str(exc))
    except Exception as exc:  # noqa: BLE001 - e.g. the bucket cannot be reached
        add(FAIL, "Backups", f"destination not reachable: {str(exc).splitlines()[0]}")

    # --- billing ---
    key = cfg.get("PAYSTACK_SECRET_KEY") or ""
    if not key:
        add(OK, "Online payments", "off (bank transfers recorded by Kayron staff)")
    elif key.startswith("sk_test_"):
        add(WARN, "Online payments", "Paystack TEST key: switch to the live key before taking real payments")
    else:
        add(OK, "Online payments", "Paystack live key set")
    from app.models.billing import BillingSettings
    bs = BillingSettings.get()
    add(OK if bs and bs.bank_details else WARN, "Invoice details",
        "" if bs and bs.bank_details else "add bank/payment instructions under Platform → Billing → Settings")
    plans = db.session.execute(select(SubscriptionPlan).where(SubscriptionPlan.is_active.is_(True))).scalars().all()
    add(OK if plans else WARN, "Subscription plans", f"{len(plans)} active" if plans else "create the plans to offer")

    # --- capacity ---
    import os
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    if workers > 1 and cfg.get("RATELIMIT_STORAGE_URI", "memory://").startswith("memory"):
        add(WARN, "Sign-in attempt limits", "several server processes count separately: set RATELIMIT_STORAGE_URI")
    else:
        add(OK, "Sign-in attempt limits")
    return out


def report(results, echo):
    width = max(len(w) for _, w, _ in results)
    for status, what, detail in results:
        echo(f"[{status:4}] {what:<{width}}  {detail}".rstrip())
    fails = sum(1 for s, _, _ in results if s == FAIL)
    warns = sum(1 for s, _, _ in results if s == WARN)
    echo("")
    echo("Ready to go live." if not fails else f"{fails} item(s) must be fixed before going live.")
    if warns:
        echo(f"{warns} item(s) to look at.")
    return fails
