import pytest

from app import create_app
from app.extensions import db as _db
from tests.conftest import PASSWORD, add_member, login, make_org, make_staff


def test_health(client):
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json["database"] == "ok"


def test_security_headers(client):
    r = client.get("/auth/login")
    csp = r.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in r.headers["Cache-Control"]


def test_no_inline_scripts_or_styles(client):
    make_org("Alpha", admin_email="admin@alpha.org")
    login(client, "admin@alpha.org")
    for url in ("/auth/login", "/register", "/o/alpha/", "/o/alpha/users", "/o/alpha/roles", "/o/alpha/settings"):
        html = client.get(url).data.decode()
        assert "<script>" not in html and "onclick=" not in html and 'style="' not in html, url


def test_csrf_enforced():
    app = create_app("testing")  # CSRF on
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        make_staff()
        c = app.test_client()
        r = c.post("/auth/login", data={"email": "super@holido.org", "password": PASSWORD})
        assert r.status_code == 400
        _db.session.remove()
        _db.drop_all()


def test_production_requires_secrets(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app("production")


def test_viewport_and_theme_on_every_layout(client):
    make_staff()
    for url in ("/", "/auth/login", "/register"):
        html = client.get(url).data.decode()
        assert 'name="viewport" content="width=device-width, initial-scale=1' in html, url
        assert "data-theme-toggle" in html, url
        assert html.index("theme-init.js") < html.index("</head>")
        assert html.index("mobile.css") > html.index("dark.css")
    login(client, "super@holido.org")
    html = client.get("/platform/").data.decode()
    assert "data-theme-toggle" in html and 'class="tabbar' in html and 'id="menu-open"' in html


def test_every_page_renders_for_admin(client):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    add_member(org, "staff@alpha.org")
    login(client, "admin@alpha.org")
    from app.models import Membership, Role
    m = Membership.query.filter_by(organization_id=org.id).first()
    r = Role.query.filter_by(organization_id=org.id).first()
    for url in (f"/o/{org.slug}/", f"/o/{org.slug}/users", f"/o/{org.slug}/users/invite",
                f"/o/{org.slug}/users/{m.id}", f"/o/{org.slug}/roles", f"/o/{org.slug}/roles/new",
                f"/o/{org.slug}/roles/{r.id}", f"/o/{org.slug}/roles/new?from={r.id}", f"/o/{org.slug}/settings",
                f"/o/{org.slug}/audit", f"/o/{org.slug}/support", "/account/", "/account/password",
                "/account/workspaces"):
        assert client.get(url).status_code == 200, url


def test_every_platform_page_renders(client):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    make_staff()
    login(client, "super@holido.org")
    for url in ("/platform/", "/platform/organizations", "/platform/organizations?status=active&q=alp",
                "/platform/organizations/new", f"/platform/organizations/{org.id}", "/platform/plans",
                "/platform/plans/new", "/platform/staff", "/platform/audit", f"/platform/audit?org={org.id}&action=auth"):
        assert client.get(url).status_code == 200, url


def test_settings_update_and_logo_validation(client, db):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    login(client, "admin@alpha.org")
    import io
    data = {"name": "Alpha Trust Ghana", "org_type": "Other", "country": "Ghana", "email": "info@alpha.org",
            "currency": "USD", "fiscal_year_start_month": "7", "timezone": "Africa/Accra",
            "logo": (io.BytesIO(b"GIF89a....."), "x.gif")}
    r = client.post(f"/o/{org.slug}/settings", data=data, content_type="multipart/form-data")
    assert b"must be a PNG, JPEG or WebP" in r.data
    data["logo"] = (io.BytesIO(b"\xff\xd8\xff" + b"0" * 50), "x.jpg")
    r = client.post(f"/o/{org.slug}/settings", data=data, content_type="multipart/form-data")
    assert r.status_code == 302
    db.session.expire_all()
    from app.models import Organization
    o = db.session.get(Organization, org.id)
    assert o.name == "Alpha Trust Ghana" and o.currency == "USD" and o.fiscal_year_start_month == 7
    assert o.logo_mime == "image/jpeg" and o.require_support_approval is False  # unchecked box


def test_sync_roles_cli(app):
    make_org("Alpha", admin_email="admin@alpha.org")
    res = app.test_cli_runner().invoke(args=["oims", "sync-roles"])
    assert res.exit_code == 0 and "1 organization" in res.output
