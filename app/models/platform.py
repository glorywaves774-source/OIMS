"""Platform-level records: subscription plans, subscriptions, support access, audit log."""
from .base import TenantMixin, TimestampMixin, as_aware, db, utcnow


class SubscriptionPlan(TimestampMixin, db.Model):
    __tablename__ = "subscription_plans"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500))
    currency = db.Column(db.String(3), nullable=False, default="GHS")
    monthly_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    annual_price = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    trial_days = db.Column(db.Integer, nullable=False, default=0)
    max_users = db.Column(db.Integer)          # NULL = unlimited
    max_storage_mb = db.Column(db.Integer)     # NULL = unlimited
    is_public = db.Column(db.Boolean, nullable=False, default=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Subscription(TimestampMixin, db.Model):
    """One subscription per organization; invoices and payments in app/models/billing.py."""

    __tablename__ = "subscriptions"

    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    STATUSES = (TRIAL, ACTIVE, PAST_DUE, EXPIRED, CANCELLED)

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=TRIAL)
    billing_cycle = db.Column(db.String(10), nullable=False, default="monthly")
    starts_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    trial_ends_at = db.Column(db.DateTime(timezone=True))
    current_period_end = db.Column(db.DateTime(timezone=True))
    # Phase 8: plan changes wait for the next period; cancellation takes effect at the period end.
    pending_plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plans.id", ondelete="SET NULL"))
    pending_cycle = db.Column(db.String(10))
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    past_due_since = db.Column(db.Date)

    organization = db.relationship("Organization", back_populates="subscription")
    plan = db.relationship("SubscriptionPlan", foreign_keys=[plan_id])
    pending_plan = db.relationship("SubscriptionPlan", foreign_keys=[pending_plan_id])


class SupportAccessRequest(TenantMixin, TimestampMixin, db.Model):
    """Time-limited, read-only, audited access by Kayron staff to a tenant workspace."""

    __tablename__ = "support_access_requests"

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    REVOKED = "revoked"
    ENDED = "ended"

    id = db.Column(db.Integer, primary_key=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reason = db.Column(db.String(1000), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=PENDING, index=True)
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    decided_at = db.Column(db.DateTime(timezone=True))
    starts_at = db.Column(db.DateTime(timezone=True))
    expires_at = db.Column(db.DateTime(timezone=True))

    organization = db.relationship("Organization")
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    decided_by = db.relationship("User", foreign_keys=[decided_by_id])

    def is_live(self):
        exp = as_aware(self.expires_at)
        return self.status == self.APPROVED and exp is not None and exp > utcnow()

    @property
    def display_status(self):
        if self.status == self.APPROVED and not self.is_live():
            return "expired"
        return self.status


class AuditLog(db.Model):
    """Append-only record of security-relevant and administrative actions."""

    __tablename__ = "audit_logs"

    id = db.Column(db.BigInteger().with_variant(db.Integer, "sqlite"), primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    actor_email = db.Column(db.String(255))
    via_support_access = db.Column(db.Boolean, nullable=False, default=False)
    action = db.Column(db.String(80), nullable=False, index=True)
    entity_type = db.Column(db.String(60))
    entity_id = db.Column(db.String(60))
    summary = db.Column(db.String(500))
    details = db.Column(db.JSON)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(300))

    organization = db.relationship("Organization")
    actor = db.relationship("User")
