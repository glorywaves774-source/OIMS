import re

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Membership, Organization, PlatformRole, Role, User
from app.rbac import seed_default_roles

PASSWORD = "Str0ng!Passphrase"


@pytest.fixture
def app():
    app = create_app("testing", {"WTF_CSRF_ENABLED": False})
    with app.app_context():
        _db.drop_all()
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    return _db


def make_user(email, name="Test Person", password=PASSWORD, platform_role=None):
    u = User(email=email, full_name=name, platform_role=platform_role)
    if password:
        u.set_password(password)
    _db.session.add(u)
    _db.session.flush()
    return u


def make_org(name, admin_email=None, status=Organization.ACTIVE):
    from app.services import unique_slug
    org = Organization(name=name, slug=unique_slug(name), org_type="Other", country="Ghana",
                       email=f"info@{name.lower().replace(' ', '')}.org", status=status)
    _db.session.add(org)
    _db.session.flush()
    admin_role = seed_default_roles(org)
    admin = None
    if admin_email:
        admin = make_user(admin_email, name=f"{name} Admin")
        _db.session.add(Membership(organization_id=org.id, user_id=admin.id, role_id=admin_role.id,
                                   status=Membership.ACTIVE))
    _db.session.commit()
    return org, admin


def add_member(org, email, role_name="Staff Member", status=Membership.ACTIVE):
    role = Role.query.filter_by(organization_id=org.id, name=role_name).one()
    user = User.query.filter_by(email=email).first() or make_user(email)
    m = Membership(organization_id=org.id, user_id=user.id, role_id=role.id, status=status)
    _db.session.add(m)
    _db.session.commit()
    return user, m


def make_staff(email="super@holido.org", role=PlatformRole.SUPER_ADMIN):
    u = make_user(email, name="Platform Person", platform_role=role)
    _db.session.commit()
    return u


def login(client, email, password=PASSWORD, follow=False):
    return client.post("/auth/login", data={"email": email, "password": password}, follow_redirects=follow)


def logout(client):
    return client.post("/auth/logout")


def extract_link(html, path_fragment="/auth/reset/"):
    m = re.search(r'value="(https?://[^"]*' + re.escape(path_fragment) + r'[^"]+)"', html)
    return m.group(1) if m else None
