"""Business operations shared by the blueprints and CLI."""
import re
import unicodedata
from datetime import timedelta

from flask import current_app

from app import audit
from app.extensions import db
from app.models import (Membership, Organization, Role, Subscription, SubscriptionPlan, User,
                        utcnow)
from app.rbac import ADMIN_ROLE_NAME, seed_default_roles
from app.security import external_url, make_password_token, send_email

LOGO_MAX_BYTES = 512 * 1024
LOGO_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
}


class ServiceError(ValueError):
    pass


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:60] or "org"


def unique_slug(name):
    base = slugify(name)
    slug, n = base, 2
    while Organization.query.filter_by(slug=slug).first():
        slug = f"{base}-{n}"
        n += 1
    return slug


def read_logo(file_storage):
    """Validate an uploaded logo by content (not filename). Returns (bytes, mime) or None."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        return None
    data = file_storage.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise ServiceError("The logo must be 512 KB or smaller.")
    for sig, mime in LOGO_SIGNATURES.items():
        if data.startswith(sig):
            return data, mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return data, "image/webp"
    raise ServiceError("The logo must be a PNG, JPEG or WebP image.")


ORG_FIELDS = ("name", "org_type", "registration_number", "address", "country", "region", "district",
              "phone", "email", "website", "description", "contact_name", "contact_phone", "contact_email")


def apply_org_fields(org, form):
    for f in ORG_FIELDS:
        setattr(org, f, getattr(form, f).data or None)
    logo = read_logo(form.logo.data)
    if logo:
        org.logo_data, org.logo_mime = logo


def _start_subscription(org, plan_id):
    if not plan_id:
        return
    plan = db.session.get(SubscriptionPlan, plan_id)
    if plan is None or not plan.is_active:
        raise ServiceError("Select an available subscription plan.")
    sub = Subscription(organization=org, plan=plan, starts_at=utcnow())
    if plan.trial_days:
        sub.status = Subscription.TRIAL
        sub.trial_ends_at = utcnow() + timedelta(days=plan.trial_days)
    else:
        sub.status = Subscription.ACTIVE
    db.session.add(sub)


def register_organization(form):
    """Public self-registration: organization and its administrator await Kayron approval."""
    admin_email = form.admin_email.data
    user = User.query.filter_by(email=admin_email).first()
    if user is not None:
        # Do not reveal account existence beyond what is needed; require sign-in instead.
        raise ServiceError("An account with this email already exists. Sign in first, or use a different email.")
    org = Organization(status=Organization.PENDING, slug=unique_slug(form.name.data))
    apply_org_fields(org, form)
    db.session.add(org)
    user = User(email=admin_email, full_name=form.admin_name.data)
    user.set_password(form.password.data)
    db.session.add(user)
    db.session.flush()
    db.session.add(Membership(organization_id=org.id, user_id=user.id, status=Membership.PENDING,
                              job_title="Organization Administrator"))
    _start_subscription(org, form.plan_id.data)
    audit.record("organization.registered", f"Registration submitted for {org.name}",
                 entity=org, organization_id=org.id, actor=user)
    return org, user


def platform_create_organization(form, actor):
    """Kayron creates and activates an organization; returns (org, admin_user, set_password_link_or_None)."""
    org = Organization(status=Organization.PENDING, slug=unique_slug(form.name.data))
    apply_org_fields(org, form)
    db.session.add(org)
    user = User.query.filter_by(email=form.admin_email.data).first()
    new_user = user is None
    if new_user:
        user = User(email=form.admin_email.data, full_name=form.admin_name.data)
        db.session.add(user)
    db.session.flush()
    db.session.add(Membership(organization_id=org.id, user_id=user.id, status=Membership.PENDING,
                              job_title="Organization Administrator"))
    _start_subscription(org, form.plan_id.data)
    audit.record("organization.created", f"{org.name} created by Kayron", entity=org, organization_id=org.id, actor=actor)
    link = approve_organization(org, actor)
    return org, user, link


DEFAULT_LEAVE_TYPES = [("Annual leave", 15), ("Sick leave", None), ("Maternity leave", None),
                       ("Paternity leave", None), ("Compassionate leave", None), ("Study leave", None),
                       ("Unpaid leave", None)]
DEFAULT_DOC_CATEGORIES = [("Policies & procedures", True), ("Contracts & agreements", True), ("Reports", False),
                          ("Minutes", False), ("Correspondence", False), ("HR records", False),
                          ("Financial records", False), ("Templates & forms", False), ("Other", False)]


DEFAULT_BUDGET_CATEGORIES = ["Personnel", "Travel and transport", "Training and workshops", "Equipment",
                             "Supplies and materials", "Contractual services", "Monitoring and evaluation",
                             "Operating costs", "Indirect costs"]


def seed_office_defaults(org):
    """Starter lists an organization can edit (only if empty): leave types, document and budget categories."""
    from app.models import BudgetCategory, DocumentCategory, LeaveType
    if not BudgetCategory.query.filter_by(organization_id=org.id).count():
        for i, name in enumerate(DEFAULT_BUDGET_CATEGORIES):
            db.session.add(BudgetCategory(organization_id=org.id, name=name, sort_order=i))
    if not LeaveType.query.filter_by(organization_id=org.id).count():
        for name, days in DEFAULT_LEAVE_TYPES:
            db.session.add(LeaveType(organization_id=org.id, name=name, days_per_year=days))
    if not DocumentCategory.query.filter_by(organization_id=org.id).count():
        for name, approval in DEFAULT_DOC_CATEGORIES:
            db.session.add(DocumentCategory(organization_id=org.id, name=name, requires_approval=approval))
    db.session.flush()


def approve_organization(org, actor):
    """Activate an organization, create its roles and activate pending memberships.

    Returns a set-password link for an administrator without a password when email
    could not be sent (so the approving admin can deliver it), else None.
    """
    if org.status not in (Organization.PENDING, Organization.REJECTED):
        raise ServiceError("Only pending organizations can be approved.")
    admin_role = seed_default_roles(org)
    seed_office_defaults(org)
    org.status = Organization.ACTIVE
    org.status_reason = None
    org.approved_at = utcnow()
    org.approved_by_id = actor.id
    link_to_show = None
    for m in Membership.query.filter_by(organization_id=org.id, status=Membership.PENDING).all():
        m.role_id = admin_role.id
        if m.user.has_password:
            m.status = Membership.ACTIVE
            send_email(m.user.email, f"{org.name} is approved on ZENTAVA OIMS",
                       f"Hello {m.user.full_name},\n\n{org.name} has been approved. Sign in at "
                       f"{external_url('auth.login')}\n")
        else:
            m.status = Membership.INVITED
            link = external_url("auth.reset_password", token=make_password_token(m.user))
            sent = send_email(m.user.email, f"Set up your ZENTAVA OIMS account for {org.name}",
                              f"Hello {m.user.full_name},\n\nSet your password to access {org.name}: {link}\n")
            if not sent:
                link_to_show = link
    audit.record("organization.approved", f"{org.name} approved", entity=org, organization_id=org.id, actor=actor)
    return link_to_show


STATUS_TRANSITIONS = {
    "suspend": ({Organization.ACTIVE}, Organization.SUSPENDED),
    "activate": ({Organization.SUSPENDED, Organization.DEACTIVATED}, Organization.ACTIVE),
    "deactivate": ({Organization.ACTIVE, Organization.SUSPENDED}, Organization.DEACTIVATED),
    "reject": ({Organization.PENDING}, Organization.REJECTED),
}


def change_organization_status(org, action, reason, actor):
    allowed_from, target = STATUS_TRANSITIONS[action]
    if org.status not in allowed_from:
        raise ServiceError(f"Cannot {action} an organization that is {org.status}.")
    org.status = target
    org.status_reason = reason or None
    audit.record(f"organization.{action}", f"{org.name}: {action}" + (f" — {reason}" if reason else ""),
                 entity=org, organization_id=org.id, actor=actor)


def invite_user(org, form, actor):
    """Add a person to an organization. Returns (membership, link_to_show_or_None)."""
    user = User.query.filter_by(email=form.email.data).first()
    if user is not None:
        existing = Membership.query.filter_by(user_id=user.id, organization_id=org.id).first()
        if existing:
            raise ServiceError("This person is already a member of the organization.")
    _enforce_user_limit(org)
    role = Role.query.filter_by(id=form.role_id.data, organization_id=org.id).first()
    if role is None:
        raise ServiceError("Choose a valid role.")
    if user is None:
        user = User(email=form.email.data, full_name=form.full_name.data)
        db.session.add(user)
        db.session.flush()
    m = Membership(user_id=user.id, organization_id=org.id, role_id=role.id, job_title=form.job_title.data or None,
                   status=Membership.ACTIVE if user.has_password else Membership.INVITED, invited_by_id=actor.id)
    db.session.add(m)
    db.session.flush()
    link_to_show = None
    if user.has_password:
        send_email(user.email, f"You were added to {org.name} on ZENTAVA OIMS",
                   f"Hello {user.full_name},\n\n{actor.full_name} added you to {org.name}. "
                   f"Sign in at {external_url('auth.login')}\n")
    else:
        link = external_url("auth.reset_password", token=make_password_token(user))
        if not send_email(user.email, f"Your ZENTAVA OIMS invitation to {org.name}",
                          f"Hello {user.full_name},\n\n{actor.full_name} invited you to {org.name}. "
                          f"Set your password: {link}\n\nThe link expires in 24 hours."):
            link_to_show = link
    audit.record("user.invited", f"{user.email} added as {role.name}", entity=m, actor=actor)
    return m, link_to_show


def _enforce_user_limit(org):
    sub = org.subscription
    if sub is None or sub.plan.max_users is None:
        return
    count = Membership.query.filter(Membership.organization_id == org.id,
                                    Membership.status != Membership.SUSPENDED).count()
    if count >= sub.plan.max_users:
        raise ServiceError(f"Your plan allows {sub.plan.max_users} users. Choose a larger plan on the Billing page.")


def active_admin_count(org_id):
    return (Membership.query.join(Role, Membership.role_id == Role.id)
            .filter(Membership.organization_id == org_id, Membership.status == Membership.ACTIVE,
                    Role.is_admin.is_(True)).count())


def is_admin_role_name(name):
    return name == ADMIN_ROLE_NAME


def setup_required():
    from app.models import PlatformRole
    return User.query.filter_by(platform_role=PlatformRole.SUPER_ADMIN).first() is None


def setup_available():
    return bool(current_app.config.get("SETUP_TOKEN")) and setup_required()
