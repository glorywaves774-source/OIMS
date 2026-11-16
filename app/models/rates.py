"""Exchange rates, entered by an organization's finance team.

A rate reads "1 <currency> = <rate> <base_currency>" and applies from its date until a newer rate for the same
pair. Base currency is the organization's main currency when the rate was entered (kept on the row, so a later
change of main currency does not change what old rates meant).
"""
from .base import TenantMixin, db, utcnow


class ExchangeRate(TenantMixin, db.Model):
    __tablename__ = "exchange_rates"
    __table_args__ = (db.UniqueConstraint("organization_id", "currency", "base_currency", "effective_on",
                                          name="uq_exchange_rates_pair_day"),)

    id = db.Column(db.Integer, primary_key=True)
    currency = db.Column(db.String(3), nullable=False)
    base_currency = db.Column(db.String(3), nullable=False)
    rate = db.Column(db.Numeric(18, 8), nullable=False)
    effective_on = db.Column(db.Date, nullable=False, index=True)
    source = db.Column(db.String(200))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    created_by = db.relationship("User")
