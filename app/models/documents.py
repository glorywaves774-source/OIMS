"""Document and records management (Phase 2)."""
from .base import TenantMixin, TimestampMixin, db, utcnow


class DocumentFolder(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "document_folders"
    __table_args__ = (db.UniqueConstraint("organization_id", "parent_id", "name", name="uq_folder_org_parent_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("document_folders.id", ondelete="CASCADE"))

    parent = db.relationship("DocumentFolder", remote_side=[id])


class DocumentCategory(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "document_categories"
    __table_args__ = (db.UniqueConstraint("organization_id", "name", name="uq_doccat_org_name"),)

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    requires_approval = db.Column(db.Boolean, nullable=False, default=False)


class Document(TenantMixin, TimestampMixin, db.Model):
    __tablename__ = "documents"

    VIS_ORG = "organization"
    VIS_DEPT = "department"
    VIS_RESTRICTED = "restricted"
    VISIBILITY = {VIS_ORG: "Everyone in the organization", VIS_DEPT: "My department",
                  VIS_RESTRICTED: "Only people I choose"}
    STATUSES = ("draft", "pending_approval", "approved", "rejected", "archived")

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(250), nullable=False)
    description = db.Column(db.Text)
    folder_id = db.Column(db.Integer, db.ForeignKey("document_folders.id", ondelete="SET NULL"), index=True)
    category_id = db.Column(db.Integer, db.ForeignKey("document_categories.id", ondelete="SET NULL"))
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id", ondelete="SET NULL"), index=True)
    visibility = db.Column(db.String(20), nullable=False, default=VIS_ORG)
    status = db.Column(db.String(20), nullable=False, default="draft", index=True)
    expiry_date = db.Column(db.Date, index=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    approved_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    approved_at = db.Column(db.DateTime(timezone=True))
    decision_note = db.Column(db.String(500))
    # Optional link to the record this document is attached to (staff, correspondence, meeting, task…)
    related_type = db.Column(db.String(40), index=True)
    related_id = db.Column(db.Integer, index=True)
    expiry_notified_at = db.Column(db.DateTime(timezone=True))

    folder = db.relationship("DocumentFolder")
    category = db.relationship("DocumentCategory")
    department = db.relationship("Department")
    owner = db.relationship("User", foreign_keys=[owner_id])
    approved_by = db.relationship("User", foreign_keys=[approved_by_id])
    versions = db.relationship("DocumentVersion", back_populates="document", order_by="DocumentVersion.version_no.desc()",
                               cascade="all, delete-orphan")
    shares = db.relationship("DocumentShare", cascade="all, delete-orphan", lazy="selectin")

    @property
    def current(self):
        return self.versions[0] if self.versions else None


class DocumentVersion(TenantMixin, db.Model):
    __tablename__ = "document_versions"
    __table_args__ = (db.UniqueConstraint("document_id", "version_no", name="uq_docversion_doc_no"),)

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_no = db.Column(db.Integer, nullable=False)
    storage_key = db.Column(db.String(200), nullable=False, unique=True)
    filename = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=False)
    sha256 = db.Column(db.String(64), nullable=False)
    note = db.Column(db.String(300))
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    document = db.relationship("Document", back_populates="versions")
    uploaded_by = db.relationship("User")


class DocumentShare(TenantMixin, db.Model):
    __tablename__ = "document_shares"
    __table_args__ = (db.UniqueConstraint("document_id", "user_id", name="uq_docshare_doc_user"),)

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)

    user = db.relationship("User")


class DocumentAccessLog(TenantMixin, db.Model):
    __tablename__ = "document_access_logs"

    id = db.Column(db.Integer, primary_key=True)
    document_id = db.Column(db.Integer, db.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    version_id = db.Column(db.Integer, db.ForeignKey("document_versions.id", ondelete="SET NULL"))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"))
    action = db.Column(db.String(20), nullable=False, default="download")
    via_support_access = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    user = db.relationship("User")
    version = db.relationship("DocumentVersion")
