import pytest

from app.models import Membership, Role, RolePermission, User
from app.tenancy import TenantIsolationError, set_tenant, unscoped
from tests.conftest import add_member, login, make_org


@pytest.fixture
def two_orgs(app):
    a, admin_a = make_org("Alpha Trust", admin_email="admin@alpha.org")
    b, admin_b = make_org("Beta Foundation", admin_email="admin@beta.org")
    return a, b


# --- Isolation at the data layer -------------------------------------------------------

def test_orm_queries_are_restricted_to_current_tenant(app, two_orgs):
    a, b = two_orgs
    with app.test_request_context():
        set_tenant(a.id)
        roles = Role.query.all()
        assert roles and all(r.organization_id == a.id for r in roles)
        assert all(m.organization_id == a.id for m in Membership.query.all())
        # Even an explicit filter for the other tenant returns nothing
        assert Role.query.filter_by(organization_id=b.id).count() == 0


def test_relationship_loads_are_restricted(app, two_orgs):
    a, b = two_orgs
    from app.extensions import db
    # A person who belongs to both organizations
    user, _ = add_member(a, "both@x.org")
    add_member(b, "both@x.org")
    db.session.expire_all()
    with app.test_request_context():
        set_tenant(a.id)
        u = User.query.filter_by(email="both@x.org").one()
        assert [m.organization_id for m in u.memberships] == [a.id]
        # Intentional cross-tenant lookup must be explicit
        from sqlalchemy import select
        allm = db.session.execute(unscoped(select(Membership).where(Membership.user_id == u.id))).scalars().all()
        assert {m.organization_id for m in allm} == {a.id, b.id}


def test_cannot_write_into_another_tenant(app, two_orgs, db):
    a, b = two_orgs
    with app.test_request_context():
        set_tenant(a.id)
        db.session.add(Role(organization_id=b.id, name="Sneaky"))
        with pytest.raises(TenantIsolationError):
            db.session.flush()
        db.session.rollback()


def test_new_rows_are_stamped_with_tenant(app, two_orgs, db):
    a, _ = two_orgs
    with app.test_request_context():
        set_tenant(a.id)
        r = Role(name="Stamped")
        db.session.add(r)
        db.session.flush()
        assert r.organization_id == a.id
        db.session.rollback()


def test_cannot_move_rows_between_tenants(app, two_orgs, db):
    a, b = two_orgs
    role = Role.query.filter_by(organization_id=a.id, name="Staff Member").one()
    role.organization_id = b.id
    with pytest.raises(TenantIsolationError):
        db.session.flush()
    db.session.rollback()


def test_tenant_rows_require_an_organization(app, db):
    db.session.add(Role(name="Orphan"))
    with pytest.raises(TenantIsolationError):
        db.session.flush()
    db.session.rollback()


# --- Isolation at the HTTP layer ---------------------------------------------------------

def test_member_cannot_open_other_workspace(client, two_orgs):
    a, b = two_orgs
    login(client, "admin@alpha.org")
    assert client.get(f"/o/{a.slug}/").status_code == 200
    assert client.get(f"/o/{b.slug}/").status_code == 404
    assert client.get(f"/o/{b.slug}/users").status_code == 404


def test_cross_tenant_ids_are_not_found(client, two_orgs):
    a, b = two_orgs
    other_member = Membership.query.filter_by(organization_id=b.id).first()
    other_role = Role.query.filter_by(organization_id=b.id).first()
    login(client, "admin@alpha.org")
    assert client.get(f"/o/{a.slug}/users/{other_member.id}").status_code == 404
    assert client.post(f"/o/{a.slug}/users/{other_member.id}/suspend").status_code == 404
    assert client.get(f"/o/{a.slug}/roles/{other_role.id}").status_code == 404
    assert client.post(f"/o/{a.slug}/roles/{other_role.id}/delete").status_code == 404


def test_cannot_assign_role_from_another_tenant(client, two_orgs):
    a, b = two_orgs
    user, m = add_member(a, "staff@alpha.org")
    foreign_role = Role.query.filter_by(organization_id=b.id, name=Role.query.filter_by(
        organization_id=b.id, is_admin=True).one().name).one()
    login(client, "admin@alpha.org")
    r = client.post(f"/o/{a.slug}/users/{m.id}", data={"role_id": foreign_role.id, "job_title": ""})
    assert r.status_code in (200, 404)  # invalid choice or not found; never applied
    from app.extensions import db
    db.session.expire_all()
    assert db.session.get(Membership, m.id).role.organization_id == a.id


def test_logo_only_visible_to_members(client, two_orgs, db):
    a, b = two_orgs
    b.logo_data, b.logo_mime = b"\x89PNG\r\n\x1a\nxx", "image/png"
    db.session.commit()
    login(client, "admin@alpha.org")
    assert client.get(f"/logo/{b.slug}").status_code == 404


def test_suspended_membership_blocks_workspace(client, two_orgs, db):
    a, _ = two_orgs
    user, m = add_member(a, "gone@alpha.org")
    login(client, "gone@alpha.org")
    assert client.get(f"/o/{a.slug}/").status_code == 200
    m.status = Membership.SUSPENDED
    db.session.commit()
    assert client.get(f"/o/{a.slug}/").status_code == 404


# --- Roles and permissions -------------------------------------------------------------------

def test_default_roles_seeded(two_orgs):
    a, _ = two_orgs
    names = {r.name for r in Role.query.filter_by(organization_id=a.id)}
    for expected in ("Organization Administrator", "Executive Director", "Programme Director", "Project Manager",
                     "MEAL Officer", "Finance Officer", "HR Officer", "Procurement Officer", "Records Officer",
                     "Department Head", "Field Officer", "Staff Member", "Read-only / Auditor"):
        assert expected in names
    auditor = Role.query.filter_by(organization_id=a.id, name="Read-only / Auditor").one()
    assert all(code.endswith(".view") for code in auditor.permission_map())
    assert "audit.view" in auditor.permission_map()


def test_staff_member_least_privilege(client, two_orgs):
    a, _ = two_orgs
    add_member(a, "staff@alpha.org")
    login(client, "staff@alpha.org")
    assert client.get(f"/o/{a.slug}/").status_code == 200
    assert client.get(f"/o/{a.slug}/users").status_code == 403
    assert client.get(f"/o/{a.slug}/users/invite").status_code == 403
    assert client.get(f"/o/{a.slug}/audit").status_code == 403
    assert client.post(f"/o/{a.slug}/settings", data={"name": "Hacked"}).status_code == 403
    assert client.get("/platform/").status_code == 403


def test_auditor_reads_but_cannot_change(client, two_orgs):
    a, _ = two_orgs
    add_member(a, "auditor@alpha.org", role_name="Read-only / Auditor")
    login(client, "auditor@alpha.org")
    assert client.get(f"/o/{a.slug}/users").status_code == 200
    assert client.get(f"/o/{a.slug}/audit").status_code == 200
    assert client.get(f"/o/{a.slug}/settings").status_code == 200
    assert client.post(f"/o/{a.slug}/settings", data={}).status_code == 403
    assert client.post(f"/o/{a.slug}/roles/new", data={"name": "X"}).status_code == 403


def test_admin_invites_user_and_link_shown_without_email(client, two_orgs):
    a, _ = two_orgs
    staff_role = Role.query.filter_by(organization_id=a.id, name="Staff Member").one()
    login(client, "admin@alpha.org")
    r = client.post(f"/o/{a.slug}/users/invite", data={"full_name": "Kofi New", "email": "kofi@alpha.org",
                                                        "role_id": staff_role.id, "job_title": "Driver"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"one-time set-password link" in r.data
    m = Membership.query.join(User, Membership.user_id == User.id).filter(User.email == "kofi@alpha.org").one()
    assert m.status == Membership.INVITED and m.organization_id == a.id


def test_custom_role_with_scopes(client, two_orgs):
    a, _ = two_orgs
    login(client, "admin@alpha.org")
    r = client.post(f"/o/{a.slug}/roles/new", data={
        "name": "Team Lead", "description": "Leads a team",
        "perm": ["users.view", "audit.view", "bogus.perm"], "scope__users.view": "department",
        "scope__audit.view": "own"})
    assert r.status_code == 302
    role = Role.query.filter_by(organization_id=a.id, name="Team Lead").one()
    assert role.permission_map() == {"users.view": "department", "audit.view": "own"}
    assert not role.is_system


def test_system_roles_are_not_editable(client, two_orgs):
    a, _ = two_orgs
    role = Role.query.filter_by(organization_id=a.id, name="Staff Member").one()
    login(client, "admin@alpha.org")
    assert client.post(f"/o/{a.slug}/roles/{role.id}", data={"name": "Renamed", "perm": ["users.manage"]}).status_code == 403
    assert client.post(f"/o/{a.slug}/roles/{role.id}/delete").status_code == 302
    assert Role.query.get(role.id) is not None


def test_last_admin_is_protected(client, two_orgs, db):
    a, _ = two_orgs
    mgr_role = Role(organization_id=a.id, name="User Manager")
    mgr_role.permissions = [RolePermission(permission_code=c) for c in ("dashboard.view", "users.view", "users.manage")]
    db.session.add(mgr_role)
    db.session.commit()
    add_member(a, "mgr@alpha.org", role_name="User Manager")
    admin_m = Membership.query.join(User, Membership.user_id == User.id).filter(User.email == "admin@alpha.org").one()
    staff_role = Role.query.filter_by(organization_id=a.id, name="Staff Member").one()
    login(client, "mgr@alpha.org")
    r = client.post(f"/o/{a.slug}/users/{admin_m.id}/suspend", follow_redirects=True)
    assert b"at least one active administrator" in r.data
    r = client.post(f"/o/{a.slug}/users/{admin_m.id}/remove", follow_redirects=True)
    assert b"at least one active administrator" in r.data
    r = client.post(f"/o/{a.slug}/users/{admin_m.id}", data={"role_id": staff_role.id, "job_title": ""}, follow_redirects=True)
    assert b"at least one active administrator" in r.data
    db.session.expire_all()
    m = db.session.get(Membership, admin_m.id)
    assert m.status == Membership.ACTIVE and m.role.is_admin


def test_second_admin_can_be_demoted(client, two_orgs, db):
    a, _ = two_orgs
    _, m2 = add_member(a, "second@alpha.org", role_name="Organization Administrator")
    staff_role = Role.query.filter_by(organization_id=a.id, name="Staff Member").one()
    login(client, "admin@alpha.org")
    client.post(f"/o/{a.slug}/users/{m2.id}", data={"role_id": staff_role.id, "job_title": "Clerk"})
    db.session.expire_all()
    assert db.session.get(Membership, m2.id).role.name == "Staff Member"


def test_cannot_change_own_access(client, two_orgs):
    a, _ = two_orgs
    own = Membership.query.join(User, Membership.user_id == User.id).filter(User.email == "admin@alpha.org").one()
    login(client, "admin@alpha.org")
    r = client.post(f"/o/{a.slug}/users/{own.id}/suspend", follow_redirects=True)
    assert b"cannot change your own access" in r.data


def test_user_limit_enforced(client, two_orgs, db):
    a, _ = two_orgs
    from app.models import Subscription, SubscriptionPlan
    plan = SubscriptionPlan(code="tiny", name="Tiny", max_users=1)
    db.session.add(plan)
    db.session.flush()
    db.session.add(Subscription(organization_id=a.id, plan_id=plan.id, status="active"))
    db.session.commit()
    staff_role = Role.query.filter_by(organization_id=a.id, name="Staff Member").one()
    login(client, "admin@alpha.org")
    r = client.post(f"/o/{a.slug}/users/invite", data={"full_name": "Extra", "email": "extra@alpha.org",
                                                        "role_id": staff_role.id}, follow_redirects=True)
    assert b"Your plan allows 1 users" in r.data
    assert User.query.filter_by(email="extra@alpha.org").first() is None
