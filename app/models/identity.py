"""Users, organizations (tenants), memberships, roles and permissions."""
from datetime import timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .base import TenantMixin, TimestampMixin, as_aware, db, utcnow


class PlatformRole:
    SUPER_ADMIN = "super_admin"
    PLATFORM_ADMIN = "platform_admin"
    SUPPORT_OFFICER = "support_officer"

    LABELS = {
        SUPER_ADMIN: "HOLIDO Super Admin",
        PLATFORM_ADMIN: "Platform Administrator",
        SUPPORT_OFFICER: "Platform Support Officer",
    }
    ALL = tuple(LABELS)


class User(UserMixin, TimestampMixin, db.Model):
    """A person. Users are global; their access to organizations comes from memberships."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)
    full_name = db.Column(db.String(200), nullable=False)
    phone = db.Column(db.String(50))
    password_hash = db.Column(db.String(255))
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)
    platform_role = db.Column(db.String(32), index=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=False)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True))
    last_login_at = db.Column(db.DateTime(timezone=True))
    password_changed_at = db.Column(db.DateTime(timezone=True))
    # Bumped on password change / forced sign-out to invalidate existing sessions.
    session_version = db.Column(db.Integer, nullable=False, default=1)

    memberships = db.relationship(
        "Membership", back_populates="user", foreign_keys="Membership.user_id", lazy="selectin"
    )

    # --- Flask-Login -------------------------------------------------------
    def get_id(self):
        return f"{self.id}.{self.session_version}"

    @property
    def is_active(self):
        return bool(self.is_enabled)

    # --- Passwords ---------------------------------------------------------
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw, method="scrypt")
        self.password_changed_at = utcnow()
        self.session_version = (self.session_version or 0) + 1

    def check_password(self, raw):
        return bool(self.password_hash) and check_password_hash(self.password_hash, raw)

    @property
    def has_password(self):
        return bool(self.password_hash)

    # --- Lockout -----------------------------------------------------------
    def is_locked(self):
        lu = as_aware(self.locked_until)
        return lu is not None and lu > utcnow()

    def register_failed_login(self, max_failures, lockout_minutes):
        self.failed_login_count = (self.failed_login_count or 0) + 1
        if self.failed_login_count >= max_failures:
            self.locked_until = utcnow() + timedelta(minutes=lockout_minutes)
            self.failed_login_count = 0
            return True
        return False

    def register_successful_login(self):
        self.failed_login_count = 0
        self.locked_until = None
        self.last_login_at = utcnow()

    # --- Platform roles ----------------------------------------------------
    @property
    def is_platform_staff(self):
        return self.platform_role in PlatformRole.ALL

    @property
    def is_super_admin(self):
        return self.platform_role == PlatformRole.SUPER_ADMIN

    @property
    def platform_role_label(self):
        return PlatformRole.LABELS.get(self.platform_role, "")

    def active_memberships(self):
        return [
            m for m in self.memberships
            if m.status == Membership.ACTIVE and m.organization.status == Organization.ACTIVE
        ]

    @property
    def initials(self):
        parts = [p for p in (self.full_name or "").split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"


class Organization(TimestampMixin, db.Model):
    """A tenant: one subscribing organization with its own isolated workspace."""

    __tablename__ = "organizations"

    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    REJECTED = "rejected"
    STATUSES = (PENDING, ACTIVE, SUSPENDED, DEACTIVATED, REJECTED)

    TYPES = (
        "Non-governmental organization (NGO)",
        "Community-based organization (CBO)",
        "Faith-based organization",
        "Development partner / donor",
        "Government agency",
        "Educational institution",
        "Health institution",
        "Private business",
        "Social enterprise",
        "Association / network",
        "Other",
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    org_type = db.Column(db.String(80), nullable=False)
    registration_number = db.Column(db.String(120))
    address = db.Column(db.String(300))
    country = db.Column(db.String(80), nullable=False)
    region = db.Column(db.String(120))
    district = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(255), nullable=False)
    website = db.Column(db.String(255))
    description = db.Column(db.Text)
    contact_name = db.Column(db.String(200))
    contact_phone = db.Column(db.String(50))
    contact_email = db.Column(db.String(255))

    logo_data = db.Column(db.LargeBinary)
    logo_mime = db.Column(db.String(40))

    status = db.Column(db.String(20), nullable=False, default=PENDING, index=True)
    status_reason = db.Column(db.String(500))
    approved_at = db.Column(db.DateTime(timezone=True))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    # Workspace settings
    require_support_approval = db.Column(db.Boolean, nullable=False, default=True)
    currency = db.Column(db.String(3), nullable=False, default="GHS")
    fiscal_year_start_month = db.Column(db.Integer, nullable=False, default=1)
    timezone = db.Column(db.String(64), nullable=False, default="Africa/Accra")

    subscription = db.relationship("Subscription", uselist=False, back_populates="organization")

    @property
    def is_active(self):
        return self.status == self.ACTIVE


class Membership(TenantMixin, TimestampMixin, db.Model):
    """Links a user to an organization with one role."""

    __tablename__ = "memberships"
    __table_args__ = (db.UniqueConstraint("user_id", "organization_id", name="uq_membership_user_org"),)

    PENDING = "pending"      # created with an organization registration awaiting approval
    INVITED = "invited"      # invited, has not yet set a password / signed in
    ACTIVE = "active"
    SUSPENDED = "suspended"
    STATUSES = (PENDING, INVITED, ACTIVE, SUSPENDED)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="RESTRICT"))
    status = db.Column(db.String(20), nullable=False, default=ACTIVE)
    job_title = db.Column(db.String(150))
    invited_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    user = db.relationship("User", back_populates="memberships", foreign_keys=[user_id])
    organization = db.relationship("Organization")
    role = db.relationship("Role")


class Role(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "roles"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_role_org_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300))
    is_system = db.Column(db.Boolean, nullable=False, default=False)
    # Administrator roles hold every permission, including ones added in later phases.
    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    permissions = db.relationship(
        "RolePermission", cascade="all, delete-orphan", lazy="selectin", back_populates="role"
    )

    def permission_map(self):
        return {p.permission_code: p.scope for p in self.permissions}


class RolePermission(db.Model):
    """A permission granted to a role, with the organizational scope it applies to."""

    __tablename__ = "role_permissions"

    SCOPE_ORGANIZATION = "organization"
    SCOPE_DEPARTMENT = "department"
    SCOPE_OWN = "own"
    SCOPES = {
        SCOPE_ORGANIZATION: "Whole organization",
        SCOPE_DEPARTMENT: "Own department",
        SCOPE_OWN: "Own records",
    }

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    permission_code = db.Column(db.String(80), primary_key=True)
    scope = db.Column(db.String(20), nullable=False, default=SCOPE_ORGANIZATION)

    role = db.relationship("Role", back_populates="permissions")
