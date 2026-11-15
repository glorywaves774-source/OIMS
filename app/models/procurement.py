"""Procurement and assets (Phase 6).

Purchase request → approval (funds checked) → quotations → selection → purchase order (approved: funds
committed on the budget line) → goods received → payment (approved by a second person; releases the
commitment). Items marked as assets become entries in the asset register when they arrive.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .base import TenantMixin, TimestampMixin, db
from .programmes import MONEY

QTY = db.Numeric(14, 2)


class Supplier(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "suppliers"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_supplier_org_code"),)

    STATUSES = ("active", "suspended", "blacklisted")
    CATEGORIES = ("Office supplies", "IT equipment", "Vehicles and transport", "Construction and works",
                  "Training and events", "Printing", "Food and catering", "Professional services",
                  "Medical supplies", "Agricultural inputs", "Other")

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(60), nullable=False, default="Other")
    contact_person = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    email = db.Column(db.String(255))
    address = db.Column(db.String(300))
    tax_id = db.Column(db.String(60))
    bank_name = db.Column(db.String(120))
    bank_account_enc = db.Column(db.Text)       # encrypted (app/crypto.py)
    status = db.Column(db.String(12), nullable=False, default="active", index=True)
    status_reason = db.Column(db.String(300))
    rating = db.Column(db.Integer)               # 1–5 after deliveries
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))


class PurchaseRequest(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "purchase_requests"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_pr_org_code"),)

    STATUSES = ("draft", "submitted", "approved", "rejected", "cancelled", "ordered", "completed")
    METHODS = {"single": "One quotation", "quotes": "At least three quotations",
               "tender": "Competitive tender (three or more bids and an evaluation report)"}

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    title = db.Column(db.String(250), nullable=False)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="CASCADE"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    budget_line_id = db.Column(db.Integer, db.ForeignKey("budget_lines.id", ondelete="RESTRICT"), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey("activities.id", ondelete="SET NULL"))
    needed_by = db.Column(db.Date)
    justification = db.Column(db.Text, nullable=False)
    delivery_location = db.Column(db.String(200))
    status = db.Column(db.String(12), nullable=False, default="draft", index=True)
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    submitted_at = db.Column(db.DateTime(timezone=True))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    decision_note = db.Column(db.String(500))
    method = db.Column(db.String(10))            # fixed when submitted, from the estimate and the thresholds
    selected_quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id", ondelete="SET NULL",
                                                                use_alter=True, name="fk_pr_selected_quotation"))
    selection_reason = db.Column(db.Text)
    evaluation_report = db.Column(db.Text)       # required for tenders

    programme = db.relationship("Programme")
    project = db.relationship("Project")
    budget_line = db.relationship("BudgetLine")
    activity = db.relationship("Activity")
    requested_by = db.relationship("User", foreign_keys=[requested_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    items = db.relationship("PurchaseRequestItem", back_populates="request", cascade="all, delete-orphan",
                            order_by="PurchaseRequestItem.id")
    quotations = db.relationship("Quotation", back_populates="request", cascade="all, delete-orphan",
                                 foreign_keys="Quotation.request_id", order_by="Quotation.total_amount")
    selected_quotation = db.relationship("Quotation", foreign_keys=[selected_quotation_id], post_update=True)

    @property
    def owner(self):
        return self.project or self.programme

    @property
    def estimated_total(self):
        return sum((i.line_total for i in self.items), Decimal(0))

    @property
    def quotes_needed(self):
        return {"single": 1, "quotes": 3, "tender": 3}.get(self.method or "single", 1)


class PurchaseRequestItem(TenantMixin, db.Model):
    __tablename__ = "purchase_request_items"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False,
                           index=True)
    description = db.Column(db.String(300), nullable=False)
    quantity = db.Column(QTY, nullable=False)
    unit = db.Column(db.String(30), nullable=False, default="each")
    unit_cost = db.Column(MONEY, nullable=False)         # estimate
    is_asset = db.Column(db.Boolean, nullable=False, default=False)
    asset_category = db.Column(db.String(40))

    request = db.relationship("PurchaseRequest", back_populates="items")

    @property
    def line_total(self):
        return (Decimal(self.quantity or 0) * Decimal(self.unit_cost or 0)).quantize(Decimal("0.01"), ROUND_HALF_UP)


class Quotation(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "quotations"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id", ondelete="CASCADE"), nullable=False,
                           index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    reference = db.Column(db.String(120))
    received_on = db.Column(db.Date, nullable=False)
    total_amount = db.Column(MONEY, nullable=False)
    delivery_days = db.Column(db.Integer)
    valid_until = db.Column(db.Date)
    notes = db.Column(db.String(500))
    recorded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    request = db.relationship("PurchaseRequest", back_populates="quotations", foreign_keys=[request_id])
    supplier = db.relationship("Supplier")


class PurchaseOrder(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "purchase_orders"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_po_org_code"),)

    STATUSES = ("draft", "approved", "partially_received", "received", "closed", "cancelled")

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("purchase_requests.id", ondelete="RESTRICT"), nullable=False,
                           index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True)
    quotation_id = db.Column(db.Integer, db.ForeignKey("quotations.id", ondelete="SET NULL"))
    order_date = db.Column(db.Date, nullable=False)
    delivery_date = db.Column(db.Date)
    terms = db.Column(db.Text)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    commitment_id = db.Column(db.Integer, db.ForeignKey("expenditures.id", ondelete="SET NULL"))
    cancel_reason = db.Column(db.String(300))

    request = db.relationship("PurchaseRequest")
    supplier = db.relationship("Supplier")
    quotation = db.relationship("Quotation")
    created_by = db.relationship("User", foreign_keys=[created_by_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    commitment = db.relationship("Expenditure", foreign_keys=[commitment_id])
    items = db.relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan",
                            order_by="PurchaseOrderItem.id")
    receipts = db.relationship("GoodsReceipt", back_populates="order", order_by="GoodsReceipt.received_on")

    @property
    def total(self):
        return sum((i.line_total for i in self.items), Decimal(0))

    @property
    def received_value(self):
        return sum(((Decimal(i.received_qty or 0) * Decimal(i.unit_price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
                    for i in self.items), Decimal(0))

    @property
    def fully_received(self):
        return all(Decimal(i.received_qty or 0) >= Decimal(i.quantity) for i in self.items)


class PurchaseOrderItem(TenantMixin, db.Model):
    __tablename__ = "purchase_order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False,
                         index=True)
    description = db.Column(db.String(300), nullable=False)
    quantity = db.Column(QTY, nullable=False)
    unit = db.Column(db.String(30), nullable=False, default="each")
    unit_price = db.Column(MONEY, nullable=False)
    received_qty = db.Column(QTY, nullable=False, default=0)
    is_asset = db.Column(db.Boolean, nullable=False, default=False)
    asset_category = db.Column(db.String(40))

    order = db.relationship("PurchaseOrder", back_populates="items")

    @property
    def line_total(self):
        return (Decimal(self.quantity) * Decimal(self.unit_price)).quantize(Decimal("0.01"), ROUND_HALF_UP)

    @property
    def outstanding(self):
        return Decimal(self.quantity) - Decimal(self.received_qty or 0)


class GoodsReceipt(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "goods_receipts"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_grn_org_code"),)

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False,
                         index=True)
    received_on = db.Column(db.Date, nullable=False)
    received_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    delivery_note = db.Column(db.String(120))
    notes = db.Column(db.String(500))
    lines = db.Column(db.JSON, nullable=False, default=list)   # [{"item_id", "description", "quantity", "condition"}]

    order = db.relationship("PurchaseOrder", back_populates="receipts")
    received_by = db.relationship("User")


# --- Assets -----------------------------------------------------------------------------------

class Asset(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "assets"
    __table_args__ = (db.UniqueConstraint("organization_id", "code", name="uq_asset_org_code"),)

    # category -> default useful life in years (straight-line depreciation)
    CATEGORIES = {"Vehicles": 5, "Motorbikes": 4, "Computers and IT": 3, "Phones and tablets": 2,
                  "Office equipment": 5, "Furniture": 7, "Generators and power": 5, "Machinery and tools": 7,
                  "Buildings and structures": 20, "Other": 5}
    STATUSES = ("in_use", "in_store", "under_repair", "lost", "disposed")
    CONDITIONS = ("new", "good", "fair", "poor", "broken")

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), nullable=False)          # tag number
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="Other", index=True)
    description = db.Column(db.Text)
    make_model = db.Column(db.String(200))
    serial_number = db.Column(db.String(120), index=True)
    purchase_date = db.Column(db.Date)
    cost = db.Column(MONEY, nullable=False, default=0)
    currency = db.Column(db.String(3), nullable=False, default="GHS")
    useful_life_years = db.Column(db.Integer, nullable=False, default=5)
    residual_value = db.Column(MONEY, nullable=False, default=0)
    programme_id = db.Column(db.Integer, db.ForeignKey("programmes.id", ondelete="SET NULL"), index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id", ondelete="SET NULL"))
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id", ondelete="SET NULL"))
    order_id = db.Column(db.Integer, db.ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True)
    location_id = db.Column(db.Integer, db.ForeignKey("locations.id", ondelete="SET NULL"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    custodian_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    condition = db.Column(db.String(10), nullable=False, default="good")
    status = db.Column(db.String(14), nullable=False, default="in_store", index=True)
    warranty_until = db.Column(db.Date)
    insured = db.Column(db.Boolean, nullable=False, default=False)
    last_verified_on = db.Column(db.Date)
    last_verified_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    # disposal (requested, then approved by someone else)
    disposal_status = db.Column(db.String(10))               # requested / approved / rejected
    disposal_method = db.Column(db.String(20))
    disposal_reason = db.Column(db.String(500))
    disposal_value = db.Column(MONEY)
    disposal_requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    disposal_approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    disposed_on = db.Column(db.Date)
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    DISPOSAL_METHODS = {"sale": "Sold", "donation": "Donated / handed to a partner or community",
                        "scrap": "Scrapped", "write_off": "Written off (lost, stolen or destroyed)",
                        "return_donor": "Returned to the donor"}

    programme = db.relationship("Programme")
    project = db.relationship("Project")
    donor = db.relationship("Donor")
    supplier = db.relationship("Supplier")
    order = db.relationship("PurchaseOrder")
    location = db.relationship("Location")
    department = db.relationship("Department")
    custodian = db.relationship("User", foreign_keys=[custodian_id])
    last_verified_by = db.relationship("User", foreign_keys=[last_verified_by_id])
    disposal_requested_by = db.relationship("User", foreign_keys=[disposal_requested_by_id])
    disposal_approved_by = db.relationship("User", foreign_keys=[disposal_approved_by_id])
    history = db.relationship("AssetEvent", back_populates="asset", cascade="all, delete-orphan",
                              order_by="AssetEvent.happened_on.desc(), AssetEvent.id.desc()")

    @property
    def owner(self):
        return self.project or self.programme

    def book_value(self, as_of=None):
        """Straight-line depreciation by whole months from the purchase date, never below the residual value."""
        cost, residual = Decimal(self.cost or 0), Decimal(self.residual_value or 0)
        if not self.purchase_date or not self.useful_life_years or cost <= residual:
            return cost
        as_of = as_of or date.today()
        months = (as_of.year - self.purchase_date.year) * 12 + as_of.month - self.purchase_date.month
        months = max(0, min(months, self.useful_life_years * 12))
        dep = (cost - residual) * months / (self.useful_life_years * 12)
        return (cost - dep).quantize(Decimal("0.01"), ROUND_HALF_UP)


class AssetEvent(TenantMixin, TimestampMixin, db.Model):
    """Everything that happens to an asset: assignment, return, transfer, maintenance, verification, disposal."""
    __tablename__ = "asset_events"

    KINDS = {"registered": "Registered", "received": "Received", "assigned": "Assigned", "returned": "Returned",
             "transferred": "Transferred", "maintenance": "Maintenance", "repair": "Repair",
             "verified": "Verified", "condition": "Condition changed", "lost": "Reported lost",
             "disposal_requested": "Disposal requested", "disposal_approved": "Disposed",
             "disposal_rejected": "Disposal refused"}

    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = db.Column(db.String(20), nullable=False)
    happened_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text)
    cost = db.Column(MONEY)
    to_user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    next_due = db.Column(db.Date)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))

    asset = db.relationship("Asset", back_populates="history")
    to_user = db.relationship("User", foreign_keys=[to_user_id])
    actor = db.relationship("User", foreign_keys=[actor_id])
