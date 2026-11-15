"""SaaS billing (Phase 8): invoices, payments and HOLIDO's billing settings.

Invoices belong to an organization (so its administrators can see them in their workspace) but are
issued and numbered by HOLIDO. Payments arrive online (Paystack) or are recorded by HOLIDO staff for
bank transfers and mobile money.
"""
from decimal import Decimal

from .base import TenantMixin, TimestampMixin, db

MONEY = db.Numeric(14, 2)


class BillingSettings(TimestampMixin, db.Model):
    """One row: what appears on invoices and how lenient billing is."""
    __tablename__ = "billing_settings"

    id = db.Column(db.Integer, primary_key=True)
    company_name = db.Column(db.String(200), nullable=False, default="HOLIDO — Holistic Development Organization")
    company_address = db.Column(db.Text)
    company_tax_id = db.Column(db.String(60))
    company_email = db.Column(db.String(255))
    bank_details = db.Column(db.Text)            # shown to organizations paying by transfer
    tax_label = db.Column(db.String(60))         # e.g. "VAT"; empty = no tax line
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)   # percent added to the plan price
    invoice_days_before = db.Column(db.Integer, nullable=False, default=7)
    grace_days = db.Column(db.Integer, nullable=False, default=14)
    invoice_footer = db.Column(db.Text)
    next_invoice_number = db.Column(db.Integer, nullable=False, default=1)

    @classmethod
    def get(cls, create=False):
        """The settings row. Without ``create`` a missing row gives unsaved defaults (no write on page views)."""
        s = db.session.get(cls, 1)
        if s is None:
            s = cls(id=1, company_name="HOLIDO — Holistic Development Organization", tax_rate=0,
                    invoice_days_before=7, grace_days=14, next_invoice_number=1)
            if create:
                db.session.add(s)
                db.session.flush()
        return s


class Invoice(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "invoices"

    STATUSES = ("open", "paid", "void")

    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(40), nullable=False, unique=True)
    subscription_id = db.Column(db.Integer, db.ForeignKey("subscriptions.id", ondelete="SET NULL"), index=True)
    plan_id = db.Column(db.Integer, db.ForeignKey("subscription_plans.id", ondelete="SET NULL"))
    billing_cycle = db.Column(db.String(10), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    issued_on = db.Column(db.Date, nullable=False)
    due_on = db.Column(db.Date, nullable=False, index=True)
    currency = db.Column(db.String(3), nullable=False)
    lines = db.Column(db.JSON, nullable=False, default=list)   # [{"description", "amount"}]
    subtotal = db.Column(MONEY, nullable=False)
    tax_label = db.Column(db.String(60))
    tax_rate = db.Column(db.Numeric(5, 2), nullable=False, default=0)
    tax_amount = db.Column(MONEY, nullable=False, default=0)
    total = db.Column(MONEY, nullable=False)
    status = db.Column(db.String(10), nullable=False, default="open", index=True)
    paid_on = db.Column(db.Date)
    void_reason = db.Column(db.String(300))
    # copies at the time of issue, so a later change of name or address does not rewrite old invoices
    bill_to = db.Column(db.JSON)
    issuer = db.Column(db.JSON)
    reminder_sent_at = db.Column(db.DateTime(timezone=True))

    organization = db.relationship("Organization")
    plan = db.relationship("SubscriptionPlan")
    payments = db.relationship("Payment", back_populates="invoice", order_by="Payment.created_at")

    @property
    def amount_paid(self):
        return sum((Decimal(p.amount) for p in self.payments if p.status == "succeeded"), Decimal(0))

    @property
    def balance(self):
        return max(Decimal(0), Decimal(self.total) - self.amount_paid)


class Payment(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "payments"

    METHODS = {"paystack": "Online (card or mobile money)", "bank_transfer": "Bank transfer",
               "mobile_money": "Mobile money", "cheque": "Cheque", "cash": "Cash", "waiver": "Waived by HOLIDO"}
    STATUSES = ("pending", "succeeded", "failed")

    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    method = db.Column(db.String(20), nullable=False)
    reference = db.Column(db.String(120), nullable=False, unique=True)   # provider or bank reference; prevents doubles
    amount = db.Column(MONEY, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    status = db.Column(db.String(10), nullable=False, default="pending", index=True)
    received_on = db.Column(db.Date)
    note = db.Column(db.String(500))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    started_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    provider_status = db.Column(db.String(40))
    channel = db.Column(db.String(40))           # card / mobile_money … as reported by the provider

    invoice = db.relationship("Invoice", back_populates="payments")
    recorded_by = db.relationship("User", foreign_keys=[recorded_by_id])
