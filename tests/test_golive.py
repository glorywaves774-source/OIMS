"""Phase 9: production safety checks, health check and go-live tooling."""
import importlib

import pytest

import app.config as cfg
from app import create_app


@pytest.fixture
def prod_env(monkeypatch, tmp_path):
    """A valid production environment; each test then breaks one thing."""
    monkeypatch.setenv("SECRET_KEY", "k3y-" + "a1B2c3D4" * 5)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("UPLOAD_ROOT", str(tmp_path))
    for k in ("STORAGE_BACKEND", "S3_BUCKET", "PUBLIC_BASE_URL", "PAYSTACK_API_BASE", "SESSION_COOKIE_SECURE",
              "RENDER"):
        monkeypatch.delenv(k, raising=False)

    def build(name="production"):
        importlib.reload(cfg)
        monkeypatch.setattr("app.CONFIGS", cfg.CONFIGS)
        return create_app(name)

    yield build, monkeypatch
    importlib.reload(cfg)


def test_valid_production_settings_start(prod_env):
    build, _ = prod_env
    assert build().config["SESSION_COOKIE_SECURE"] is True


@pytest.mark.parametrize("name,value,message", [
    ("SECRET_KEY", "dev-only-not-secret", "SECRET_KEY"),
    ("SECRET_KEY", "short", "SECRET_KEY"),
    ("SESSION_COOKIE_SECURE", "false", "SESSION_COOKIE_SECURE"),
    ("PUBLIC_BASE_URL", "http://zentava.example.org", "PUBLIC_BASE_URL"),
    ("PAYSTACK_API_BASE", "http://api.paystack.co", "PAYSTACK_API_BASE"),
])
def test_unsafe_production_settings_refuse_to_start(prod_env, name, value, message):
    build, mp = prod_env
    mp.setenv(name, value)
    with pytest.raises(RuntimeError, match=message):
        build()


def test_development_settings_refused_on_the_server(prod_env):
    build, mp = prod_env
    mp.setenv("RENDER", "true")
    with pytest.raises(RuntimeError, match="OIMS_ENV"):
        build("development")


@pytest.mark.parametrize("target,ok", [
    ("/o/acme/tasks/", True), ("/account/", True),
    ("//evil.example", False), ("/\\evil.example", False), ("/\\/evil.example", False), ("/\t/evil.example", False),
    ("https://evil.example", False), ("javascript:alert(1)", False), ("", False), (None, False),
])
def test_return_address_after_sign_in_stays_on_site(target, ok):
    from app.security import is_safe_next
    assert is_safe_next(target) is ok


def test_page_links_keep_their_address_values(app):
    """The pager keeps ids and filters in its links, and can use its own page parameter."""
    from flask import render_template_string
    from app.extensions import db as _db

    class P:
        pages, page, has_prev, has_next, prev_num, next_num, total = 3, 2, True, True, 1, 3, 70

        def iter_pages(self, **kw):
            return [1, 2, 3]
    with app.test_request_context():
        app.url_map  # routes are registered
        html = render_template_string(
            '{% from "macros.html" import pager %}{{ pager(p, "meal.submissions", org_slug="acme", fid=7, status="all") }}'
            '{{ pager(p, "procurement.index", param="opage", org_slug="acme", view="mine", page=4) }}', p=P())
    assert "/o/acme/meal/forms/7/answers?" in html and "page=3" in html and "status=all" in html
    assert "opage=3" in html and "page=4" in html and "view=mine" in html


def test_switch_workspace_link_inside_a_workspace(client, db):
    """Someone in two organizations sees 'My workspaces' while working inside one of them."""
    from tests.conftest import add_member, login, make_org
    from app.tenancy import clear_tenant
    a, admin = make_org("Alpha Trust", admin_email="both@alpha.org")
    clear_tenant()
    b, _ = make_org("Beta Trust")
    clear_tenant()
    add_member(b, "both@alpha.org")
    clear_tenant()
    login(client, "both@alpha.org")
    html = client.get(f"/o/{a.slug}/").get_data(as_text=True)
    assert "/account/workspaces" in html
    page = client.get("/account/workspaces").get_data(as_text=True)
    assert "Alpha Trust" in page and "Beta Trust" in page


def test_large_downloads_take_turns(app, client, db):
    """While one large download is being prepared, another gets a clear 'try again' page (503)."""
    from tests.conftest import login, make_org
    from app.security import _download_slots
    org, _ = make_org("Turn Trust", admin_email="admin@turn.org")
    login(client, "admin@turn.org")
    app.config["HEAVY_DOWNLOAD_WAIT"] = 0
    url = f"/o/{org.slug}/reports/staff.csv"
    assert client.get(url).status_code == 200
    with app.app_context():
        slots = _download_slots()
    assert slots.acquire(timeout=1)          # someone else's download is in progress
    try:
        r = client.get(url)
        assert r.status_code == 503 and r.headers["Retry-After"] == "60"
        assert b"Another download is being prepared" in r.data
    finally:
        slots.release()
    assert client.get(url).status_code == 200
    app.config["HEAVY_DOWNLOAD_WAIT"] = 20


def test_email_checks_the_mail_server_certificate(app, monkeypatch):
    import smtplib
    import ssl
    from app.security import send_email
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            seen["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            seen["context"] = context

        def login(self, u, p):
            pass

        def send_message(self, msg):
            seen["to"] = msg["To"]

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    app.config.update(SMTP_HOST="smtp.example.org", SMTP_USE_TLS=True, SMTP_USERNAME="u", SMTP_PASSWORD="p")
    with app.app_context():
        assert send_email("someone@example.org", "Hello", "Body") is True
    ctx = seen["context"]
    assert ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    app.config.update(SMTP_HOST=None)


def test_health_check_does_not_reveal_the_version(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.get_json() == {"status": "ok", "database": "ok"}


def test_go_live_check_reports_plainly(app, db, tmp_path, monkeypatch):
    """The check finds what is missing and passes once it is set."""
    from app import backup as bk
    from app.golive import FAIL, OK, WARN, report, run_checks
    from app.models import PlatformRole
    from tests.conftest import make_staff
    app.config.update(PUBLIC_BASE_URL=None, BACKUP_ENCRYPTION_KEY=None, BACKUP_DIR=None, SETUP_TOKEN="t0k3n")
    res = {w: s for s, w, _ in run_checks()}
    assert res["Production settings"] == FAIL            # the test settings, not production
    assert res["Public web address"] == FAIL
    assert res["Kayron Super Admin exists"] == FAIL
    assert res["Backups"] == FAIL
    assert res["Document storage works"] == OK
    make_staff(role=PlatformRole.SUPER_ADMIN)
    app.config.update(PUBLIC_BASE_URL="https://app.zentava.example", REQUIRE_PLATFORM_2FA=True,
                      BACKUP_ENCRYPTION_KEY=bk.new_key(), BACKUP_DIR=str(tmp_path / "b"))
    res = {w: s for s, w, _ in run_checks()}
    assert res["Public web address"] == OK and res["Kayron Super Admin exists"] == OK
    assert res["First-run setup token removed"] == FAIL   # a Super Admin exists, so the token must go
    assert res["Backups"] == WARN                         # set up, none made yet
    assert res["Kayron staff have set up two-step sign-in"] == WARN
    lines = []
    assert report(run_checks(), lines.append) >= 1
    assert any("must be fixed" in line for line in lines)
    app.config.update(SETUP_TOKEN=None, REQUIRE_PLATFORM_2FA=False, BACKUP_ENCRYPTION_KEY=None, BACKUP_DIR=None,
                      PUBLIC_BASE_URL=None)
