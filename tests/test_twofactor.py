"""Phase 2: two-step sign-in."""
import re

import pyotp
import pytest

from app.models import AuditLog, PlatformRole, User
from tests.conftest import PASSWORD, login, logout, make_staff


def enroll(client):
    html = client.get("/account/two-step").data.decode()
    secret = re.search(r'id="secret" readonly value="([A-Z2-7]+)"', html).group(1)
    code = pyotp.TOTP(secret).now()
    r = client.post("/account/two-step", data={"code": code}, follow_redirects=True)
    codes = re.findall(r"<li>([0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4})</li>", r.data.decode())
    return secret, codes


def test_enroll_and_sign_in_with_code(client, db):
    make_staff()
    login(client, "super@holido.org")
    secret, codes = enroll(client)
    assert len(codes) == 10
    u = User.query.filter_by(email="super@holido.org").one()
    assert u.has_2fa and secret not in (u.totp_secret_enc or "")  # stored encrypted
    assert all(c not in str(u.recovery_codes) for c in codes)    # stored hashed
    logout(client)

    r = login(client, "super@holido.org")
    assert r.headers["Location"].endswith("/auth/two-step")
    assert client.get("/platform/").status_code == 302  # not signed in yet
    r = client.post("/auth/two-step", data={"code": "000000"})
    assert b"not correct" in r.data
    # A fresh code (next time step) works once; reusing it is refused
    totp = pyotp.TOTP(secret)
    import time
    code = totp.at(time.time() + 30)
    assert client.post("/auth/two-step", data={"code": code}).status_code == 302
    assert client.get("/platform/").status_code == 200
    logout(client)
    login(client, "super@holido.org")
    r = client.post("/auth/two-step", data={"code": code})
    assert b"not correct" in r.data  # replay refused


def test_recovery_code_works_once(client, db):
    make_staff()
    login(client, "super@holido.org")
    _, codes = enroll(client)
    logout(client)
    login(client, "super@holido.org")
    assert client.post("/auth/two-step", data={"code": codes[0]}).status_code == 302
    assert AuditLog.query.filter_by(action="auth.recovery_code_used").count() == 1
    logout(client)
    login(client, "super@holido.org")
    assert b"not correct" in client.post("/auth/two-step", data={"code": codes[0]}).data


def test_wrong_codes_lock_the_account(app, client, db):
    make_staff()
    login(client, "super@holido.org")
    enroll(client)
    logout(client)
    login(client, "super@holido.org")
    for _ in range(app.config["LOGIN_MAX_FAILURES"]):
        client.post("/auth/two-step", data={"code": "123456"})
    assert User.query.filter_by(email="super@holido.org").one().is_locked()


def test_platform_staff_must_enroll(app, client):
    app.config["REQUIRE_PLATFORM_2FA"] = True
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    login(client, "support@holido.org")
    r = client.get("/platform/")
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/two-step")
    enroll(client)
    assert client.get("/platform/").status_code == 200
    # cannot switch it off while required
    r = client.post("/account/two-step/disable", data={"password": PASSWORD, "code": "000000"}, follow_redirects=True)
    assert b"required for Kayron platform staff" in r.data


def test_optional_for_organization_users_and_disable(client, db):
    from tests.conftest import make_org
    make_org("Alpha", admin_email="admin@alpha.org")
    login(client, "admin@alpha.org")
    assert client.get("/o/alpha/").status_code == 200  # not forced
    secret, _ = enroll(client)
    u = User.query.filter_by(email="admin@alpha.org").one()
    import time
    code = pyotp.TOTP(secret).at(time.time() + 30)  # next step (not yet used)
    r = client.post("/account/two-step/disable", data={"password": PASSWORD, "code": code}, follow_redirects=True)
    assert b"is off" in r.data
    db.session.expire_all()
    assert not db.session.get(User, u.id).has_2fa


@pytest.mark.parametrize("bad", ["", "12345", "abcdef", "1234567"])
def test_code_format(bad):
    from app.twofactor import check_code
    assert check_code(pyotp.random_base32(), bad) is None


def test_admins_can_reset_two_step(client, app, db):
    from app.models import Membership
    from tests.conftest import add_member, make_org
    org, _ = make_org("Beta", admin_email="admin@beta.org")
    user, m = add_member(org, "lost@beta.org")
    other = app.test_client()
    login(other, "lost@beta.org")
    enroll(other)
    assert User.query.filter_by(email="lost@beta.org").one().has_2fa
    login(client, "admin@beta.org")
    client.post(f"/o/{org.slug}/users/{m.id}/reset-2fa")
    db.session.expire_all()
    assert not db.session.get(User, user.id).has_2fa
    assert other.get(f"/o/{org.slug}/").status_code == 302  # signed out
    assert AuditLog.query.filter_by(action="user.2fa_reset").count() == 1
    # Organization admins cannot reset HOLIDO staff
    staff = make_staff("help@holido.org", PlatformRole.SUPPORT_OFFICER)
    db.session.add(Membership(organization_id=org.id, user_id=staff.id, status="active",
                              role_id=m.role_id))
    db.session.commit()
    sm = Membership.query.filter_by(user_id=staff.id).one()
    assert client.post(f"/o/{org.slug}/users/{sm.id}/reset-2fa").status_code == 403
