from datetime import timedelta

from app.models import AuditLog, Membership, Organization, PlatformRole, User, utcnow
from app.security import make_password_token
from tests.conftest import PASSWORD, add_member, login, logout, make_org, make_staff


# --- First-run setup ----------------------------------------------------------

def _setup_data(**over):
    data = {"setup_token": "test-setup-token", "full_name": "Ama Owner", "email": "owner@holido.org",
            "password": PASSWORD, "confirm": PASSWORD}
    data.update(over)
    return data


def test_setup_requires_token_configured(app, client):
    app.config["SETUP_TOKEN"] = None
    assert client.get("/setup/").status_code == 404


def test_setup_rejects_wrong_token(client):
    r = client.post("/setup/", data=_setup_data(setup_token="nope"))
    assert r.status_code == 200
    assert b"setup token is not correct" in r.data
    assert User.query.count() == 0


def test_setup_rejects_weak_password(client):
    r = client.post("/setup/", data=_setup_data(password="short", confirm="short"))
    assert b"at least 12 characters" in r.data
    assert User.query.count() == 0


def test_setup_creates_super_admin_once(client):
    r = client.post("/setup/", data=_setup_data())
    assert r.status_code == 302 and r.headers["Location"].endswith("/platform/")
    u = User.query.one()
    assert u.platform_role == PlatformRole.SUPER_ADMIN
    assert u.password_hash.startswith("scrypt:") and PASSWORD not in u.password_hash
    # Locked forever after the first Super Admin exists
    assert client.get("/setup/").status_code == 404
    assert client.post("/setup/", data=_setup_data(email="x@y.org")).status_code == 404


def test_cli_create_superadmin(app, monkeypatch):
    monkeypatch.setenv("OIMS_SUPERADMIN_EMAIL", "Admin@Holido.org")
    monkeypatch.setenv("OIMS_SUPERADMIN_PASSWORD", PASSWORD)
    runner = app.test_cli_runner()
    res = runner.invoke(args=["oims", "create-superadmin"])
    assert res.exit_code == 0, res.output
    u = User.query.filter_by(email="admin@holido.org").one()
    assert u.is_super_admin and u.must_change_password
    again = runner.invoke(args=["oims", "create-superadmin"])
    assert again.exit_code != 0 and "already exists" in again.output


def test_cli_rejects_weak_password(app, monkeypatch):
    monkeypatch.setenv("OIMS_SUPERADMIN_EMAIL", "a@holido.org")
    monkeypatch.setenv("OIMS_SUPERADMIN_PASSWORD", "password")
    res = app.test_cli_runner().invoke(args=["oims", "create-superadmin"])
    assert res.exit_code != 0
    assert User.query.count() == 0


# --- Sign-in ----------------------------------------------------------------------

def test_login_success_and_logout(client):
    make_staff()
    r = login(client, "super@holido.org")
    assert r.status_code == 302
    assert client.get("/platform/").status_code == 200
    assert AuditLog.query.filter_by(action="auth.login").count() == 1
    assert client.get("/auth/logout").status_code == 405  # sign-out is POST only
    logout(client)
    assert client.get("/platform/").status_code == 302


def test_login_generic_failure_messages(client):
    make_staff()
    a = login(client, "super@holido.org", "Wrong!Password1", follow=True)
    b = login(client, "nobody@holido.org", "Wrong!Password1", follow=True)
    assert b"Email or password is incorrect." in a.data
    assert b"Email or password is incorrect." in b.data


def test_lockout_after_repeated_failures(app, client):
    make_staff()
    for _ in range(app.config["LOGIN_MAX_FAILURES"]):
        login(client, "super@holido.org", "Wrong!Password1")
    r = login(client, "super@holido.org", PASSWORD, follow=True)
    assert b"temporarily locked" in r.data
    assert User.query.one().is_locked()
    assert AuditLog.query.filter_by(action="auth.locked").count() == 1


def test_lockout_expires(app, client, db):
    u = make_staff()
    u.locked_until = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert login(client, "super@holido.org").status_code == 302


def test_disabled_user_cannot_sign_in(client, db):
    u = make_staff()
    u.is_enabled = False
    db.session.commit()
    r = login(client, "super@holido.org", follow=True)
    assert b"Email or password is incorrect." in r.data


def test_open_redirect_blocked(client):
    make_staff()
    r = client.post("/auth/login?next=https://evil.example/", data={"email": "super@holido.org", "password": PASSWORD})
    assert "evil.example" not in r.headers["Location"]
    client.post("/auth/logout")
    r = client.post("/auth/login?next=/account/", data={"email": "super@holido.org", "password": PASSWORD})
    assert r.headers["Location"].endswith("/account/")


def test_pending_org_member_cannot_sign_in(client):
    org, admin = make_org("Pending Org", status=Organization.PENDING)
    from tests.conftest import make_user as mu
    from app.extensions import db
    u = mu("waiting@pending.org")
    db.session.add(Membership(organization_id=org.id, user_id=u.id, status=Membership.PENDING))
    db.session.commit()
    r = login(client, "waiting@pending.org", follow=True)
    assert b"awaiting approval" in r.data
    assert client.get("/account/").status_code == 302


def test_suspended_org_member_cannot_sign_in(client, db):
    org, admin = make_org("Paused Org", admin_email="admin@paused.org")
    org.status = Organization.SUSPENDED
    db.session.commit()
    r = login(client, "admin@paused.org", follow=True)
    assert b"suspended" in r.data


# --- Passwords ---------------------------------------------------------------------

def test_forced_password_change(client, db):
    u = make_staff()
    u.must_change_password = True
    db.session.commit()
    login(client, "super@holido.org")
    r = client.get("/platform/")
    assert r.status_code == 302 and "/account/password" in r.headers["Location"]
    new = "An0ther!Passphrase"
    r = client.post("/account/password", data={"current_password": PASSWORD, "password": new, "confirm": new})
    assert r.status_code == 302
    assert client.get("/platform/").status_code == 200


def test_password_change_signs_out_other_sessions(app, client, db):
    make_staff()
    other = app.test_client()
    login(client, "super@holido.org")
    login(other, "super@holido.org")
    new = "An0ther!Passphrase"
    client.post("/account/password", data={"current_password": PASSWORD, "password": new, "confirm": new})
    assert client.get("/platform/").status_code == 200
    assert other.get("/platform/").status_code == 302  # old session invalidated


def test_password_reset_flow_single_use(client, db):
    u = make_staff()
    r = client.post("/auth/forgot", data={"email": "super@holido.org"}, follow_redirects=True)
    assert b"If an account exists" in r.data
    r2 = client.post("/auth/forgot", data={"email": "ghost@holido.org"}, follow_redirects=True)
    assert b"If an account exists" in r2.data  # no account enumeration
    token = make_password_token(u)
    new = "Res3t!Passphrase"
    assert client.post(f"/auth/reset/{token}", data={"password": new, "confirm": new}).status_code == 302
    assert login(client, "super@holido.org", new).status_code == 302
    logout(client)
    # The same token cannot be reused after the password changed
    r = client.post(f"/auth/reset/{token}", data={"password": "Other!Passphrase9", "confirm": "Other!Passphrase9"})
    assert r.status_code == 302 and "/auth/forgot" in r.headers["Location"]


def test_bad_reset_token(client):
    r = client.get("/auth/reset/not-a-token")
    assert r.status_code == 302


def test_invited_user_activates_by_setting_password(client, db):
    org, admin = make_org("Invite Org", admin_email="admin@invite.org")
    user, m = add_member(org, "new@invite.org", status=Membership.INVITED)
    user.password_hash = None
    db.session.commit()
    token = make_password_token(user)
    new = "W3lcome!Aboard"
    client.post(f"/auth/reset/{token}", data={"password": new, "confirm": new})
    assert db.session.get(Membership, m.id).status == Membership.ACTIVE
    assert login(client, "new@invite.org", new).status_code == 302
