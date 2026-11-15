import io
from datetime import timedelta

from app.models import (AuditLog, Membership, Organization, PlatformRole, Role, Subscription,
                        SubscriptionPlan, SupportAccessRequest, User, utcnow)
from tests.conftest import PASSWORD, extract_link, login, logout, make_org, make_staff

REG = {
    "name": "Hope for Girls Ghana", "org_type": "Non-governmental organization (NGO)", "country": "Ghana",
    "region": "Northern", "district": "Tamale Metropolitan", "email": "info@hopegirls.org",
    "website": "https://hopegirls.org", "admin_name": "Abena Mensah", "admin_email": "abena@hopegirls.org",
    "password": PASSWORD, "confirm": PASSWORD, "accept": "y", "plan_id": "0",
}


def test_platform_requires_staff(client):
    make_org("Alpha", admin_email="admin@alpha.org")
    login(client, "admin@alpha.org")
    for url in ("/platform/", "/platform/organizations", "/platform/plans", "/platform/staff", "/platform/audit"):
        assert client.get(url).status_code == 403, url


def test_anonymous_redirected_to_login(client):
    r = client.get("/platform/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_registration_approval_lifecycle(client, db):
    plan = SubscriptionPlan(code="starter", name="Starter", trial_days=30, is_public=True)
    db.session.add(plan)
    db.session.commit()
    data = dict(REG, plan_id=str(plan.id),
                logo=(io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), "logo.png"))
    r = client.post("/register", data=data, content_type="multipart/form-data")
    assert r.status_code == 200 and b"submitted to HOLIDO" in r.data
    org = Organization.query.one()
    assert org.status == Organization.PENDING and org.logo_mime == "image/png"
    assert org.subscription.status == Subscription.TRIAL and org.subscription.trial_ends_at is not None
    assert Role.query.filter_by(organization_id=org.id).count() == 0  # roles only on approval

    # Applicant cannot sign in yet
    assert b"awaiting approval" in login(client, "abena@hopegirls.org", follow=True).data

    make_staff()
    login(client, "super@holido.org")
    assert client.get("/platform/").status_code == 200
    assert client.get(f"/platform/organizations/{org.id}").status_code == 200
    r = client.post(f"/platform/organizations/{org.id}/approve")
    assert r.status_code == 302
    db.session.expire_all()
    org = db.session.get(Organization, org.id)
    assert org.status == Organization.ACTIVE
    m = Membership.query.filter_by(organization_id=org.id).one()
    assert m.status == Membership.ACTIVE and m.role.is_admin
    logout(client)

    assert login(client, "abena@hopegirls.org").status_code == 302
    r = client.get("/account/home")
    assert r.headers["Location"].endswith(f"/o/{org.slug}/")
    assert client.get(f"/o/{org.slug}/").status_code == 200
    assert client.get(f"/logo/{org.slug}").status_code == 200


def test_registration_rejects_disguised_logo(client):
    data = dict(REG, logo=(io.BytesIO(b"<svg onload=alert(1)></svg>"), "logo.png"))
    r = client.post("/register", data=data, content_type="multipart/form-data")
    assert b"must be a PNG, JPEG or WebP" in r.data
    assert Organization.query.count() == 0


def test_registration_duplicate_email(client):
    make_staff("abena@hopegirls.org")
    r = client.post("/register", data=REG)
    assert b"already exists" in r.data
    assert Organization.query.count() == 0


def test_suspend_and_reactivate(client, db):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    member = client.application.test_client()
    login(member, "admin@alpha.org")
    assert member.get(f"/o/{org.slug}/").status_code == 200

    make_staff()
    login(client, "super@holido.org")
    client.post(f"/platform/organizations/{org.id}/status/suspend", data={"reason": "Unpaid invoice"})
    assert db.session.get(Organization, org.id).status == Organization.SUSPENDED
    assert member.get(f"/o/{org.slug}/").status_code == 403
    client.post(f"/platform/organizations/{org.id}/status/activate", data={"reason": ""})
    assert member.get(f"/o/{org.slug}/").status_code == 200
    assert AuditLog.query.filter_by(action="organization.suspend").count() == 1
    # Invalid transition
    r = client.post(f"/platform/organizations/{org.id}/status/reject", follow_redirects=True)
    assert b"Cannot reject" in r.data


def test_platform_creates_org_and_shows_link_without_email(client, db):
    make_staff()
    login(client, "super@holido.org")
    data = {"name": "Volta Water Trust", "org_type": "Other", "country": "Ghana", "email": "hq@volta.org",
            "admin_name": "Yaw Boateng", "admin_email": "yaw@volta.org", "plan_id": "0"}
    r = client.post("/platform/organizations/new", data=data, follow_redirects=True)
    assert r.status_code == 200
    link = extract_link(r.data.decode())
    assert link, "set-password link should be shown once"
    org = Organization.query.filter_by(name="Volta Water Trust").one()
    assert org.status == Organization.ACTIVE
    m = Membership.query.filter_by(organization_id=org.id).one()
    assert m.status == Membership.INVITED
    logout(client)
    path = link.split("://", 1)[1].split("/", 1)[1]
    new = "V0lta!Passphrase"
    client.post("/" + path, data={"password": new, "confirm": new})
    assert login(client, "yaw@volta.org", new).status_code == 302
    assert client.get(f"/o/{org.slug}/").status_code == 200


def test_support_officer_limits(client):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org", status=Organization.PENDING)
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    login(client, "support@holido.org")
    assert client.get("/platform/").status_code == 200
    assert client.get("/platform/organizations").status_code == 200
    assert client.post(f"/platform/organizations/{org.id}/approve").status_code == 403
    assert client.get("/platform/plans").status_code == 403
    assert client.get("/platform/staff").status_code == 403
    assert client.get("/platform/organizations/new").status_code == 403


def test_plans_and_assignment(client, db):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    make_staff()
    login(client, "super@holido.org")
    r = client.post("/platform/plans/new", data={"code": "standard", "name": "Standard", "currency": "GHS",
                                                 "monthly_price": "450.00", "annual_price": "4500.00",
                                                 "trial_days": "14", "max_users": "25", "is_public": "y",
                                                 "is_active": "y"})
    assert r.status_code == 302
    plan = SubscriptionPlan.query.filter_by(code="standard").one()
    r = client.post("/platform/plans/new", data={"code": "standard", "name": "Dup", "currency": "GHS",
                                                 "monthly_price": "1", "annual_price": "1", "trial_days": "0"})
    assert b"already uses this code" in r.data
    client.post(f"/platform/organizations/{org.id}/plan", data={"plan_id": plan.id, "status": "active",
                                                               "billing_cycle": "annual", "current_period_end": "2027-06-30"})
    sub = Subscription.query.filter_by(organization_id=org.id).one()
    assert sub.plan_id == plan.id and sub.billing_cycle == "annual" and sub.current_period_end.year == 2027


def test_staff_management(client, db):
    make_staff()
    login(client, "super@holido.org")
    r = client.post("/platform/staff", data={"full_name": "Esi Support", "email": "esi@holido.org",
                                             "platform_role": PlatformRole.SUPPORT_OFFICER})
    assert r.status_code == 200 and b"one-time set-password link" in r.data
    esi = User.query.filter_by(email="esi@holido.org").one()
    assert esi.platform_role == PlatformRole.SUPPORT_OFFICER
    client.post(f"/platform/staff/{esi.id}/remove")
    assert db.session.get(User, esi.id).platform_role is None
    me = User.query.filter_by(email="super@holido.org").one()
    r = client.post(f"/platform/staff/{me.id}/remove", follow_redirects=True)
    assert b"cannot change your own" in r.data


# --- Support access -------------------------------------------------------------------

def _request_support(client, org):
    client.post(f"/platform/organizations/{org.id}/support",
                data={"reason": "Investigating a reported login problem", "duration_minutes": 30})
    return SupportAccessRequest.query.filter_by(organization_id=org.id).order_by(SupportAccessRequest.id.desc()).first()


def test_support_access_requires_org_approval_and_is_read_only(app, client, db):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    login(client, "support@holido.org")

    # No access without a request
    assert client.get(f"/o/{org.slug}/").status_code == 404

    req = _request_support(client, org)
    assert req.status == SupportAccessRequest.PENDING
    r = client.post(f"/platform/support/{req.id}/enter", follow_redirects=True)
    assert b"not active" in r.data
    assert client.get(f"/o/{org.slug}/").status_code == 404

    # Organization admin approves
    admin = app.test_client()
    login(admin, "admin@alpha.org")
    assert b"Investigating a reported login problem" in admin.get(f"/o/{org.slug}/support").data
    admin.post(f"/o/{org.slug}/support/{req.id}/approve")
    db.session.expire_all()
    assert db.session.get(SupportAccessRequest, req.id).is_live()

    # Support enters: read-only
    client.post(f"/platform/support/{req.id}/enter")
    r = client.get(f"/o/{org.slug}/users")
    assert r.status_code == 200 and b"read-only" in r.data
    assert client.post(f"/o/{org.slug}/settings", data={"name": "Changed"}).status_code == 403
    assert client.post(f"/o/{org.slug}/roles/new", data={"name": "X"}).status_code == 403
    assert AuditLog.query.filter_by(action="support.viewed", organization_id=org.id).count() >= 1
    assert AuditLog.query.filter_by(organization_id=org.id, via_support_access=True).count() >= 1

    # Revocation ends access immediately
    admin.post(f"/o/{org.slug}/support/{req.id}/revoke")
    assert client.get(f"/o/{org.slug}/users").status_code == 302


def test_support_access_expires(client, db):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    org.require_support_approval = False
    db.session.commit()
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    login(client, "support@holido.org")
    req = _request_support(client, org)
    assert req.status == SupportAccessRequest.APPROVED  # auto-approved by org preference
    client.post(f"/platform/support/{req.id}/enter")
    assert client.get(f"/o/{org.slug}/").status_code == 200
    req.expires_at = utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert client.get(f"/o/{org.slug}/").status_code == 302


def test_support_access_is_personal(app, client, db):
    org, _ = make_org("Alpha", admin_email="admin@alpha.org")
    org.require_support_approval = False
    db.session.commit()
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    make_staff("other@holido.org", PlatformRole.SUPPORT_OFFICER)
    login(client, "support@holido.org")
    req = _request_support(client, org)
    other = app.test_client()
    login(other, "other@holido.org")
    r = other.post(f"/platform/support/{req.id}/enter", follow_redirects=True)
    assert b"not active" in r.data
    assert other.get(f"/o/{org.slug}/").status_code == 404
