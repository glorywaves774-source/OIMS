"""Document and records management."""
from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import exists, func, or_, select

from app import audit
from app.blueprints.people import department_choices
from app.blueprints.tenant import member_choices, my_department_id, page_arg, workspace_blueprint
from app.extensions import db
from app.forms import ActionForm
from app.forms_office import CategoryForm, DecisionForm, DocumentForm, FolderForm, UploadForm, VersionForm
from app.models import (Activity, Correspondence, Department, Document, Evaluation, Programme, Project, DocumentAccessLog, DocumentCategory, DocumentFolder,
                        DocumentShare, DocumentVersion, Meeting, StaffProfile, Task, utcnow)
from app.notify import notify
from app.rbac import can, require_permission
from app.storage import StorageError, UploadRejected, get_storage, inspect_upload, new_key
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("documents", __name__, "/documents")

RELATED = {"staff": StaffProfile, "correspondence": Correspondence, "meeting": Meeting, "task": Task,
           "programme": Programme, "project": Project, "activity": Activity, "evaluation": Evaluation,
           "deliverable": None, "issue": None}


def _programme_of(related_type, obj):
    """The programme or project an attachment's parent record belongs to."""
    if related_type in ("programme", "project"):
        return obj
    from app.programme_logic import owner_of
    return owner_of(obj)


def _related_model(related_type):
    from app.models import Deliverable, Issue
    return {"deliverable": Deliverable, "issue": Issue}.get(related_type) or RELATED.get(related_type)


# --- Access rules ----------------------------------------------------------------------

def parent_visible(related_type, related_id):
    """Attachments inherit visibility from the record they belong to."""
    model = _related_model(related_type)
    if model is None:
        return False
    obj = db.session.get(model, related_id)
    if obj is None or obj.organization_id != g.tenant.id:
        return False
    if related_type == "staff":
        from app.blueprints.people import can_see_records
        return can_see_records(obj)
    if related_type == "correspondence":
        from app.blueprints.correspondence import can_view_correspondence
        return can_view_correspondence(obj)
    if related_type == "meeting":
        from app.blueprints.meetings import can_view_meeting
        return can_view_meeting(obj)
    if related_type == "task":
        from app.blueprints.tasks import can_view_task
        return can_view_task(obj)
    if related_type in ("programme", "project", "activity", "evaluation", "deliverable", "issue"):
        from app.programme_logic import can_see
        prog = _programme_of(related_type, obj)
        if prog is None:
            return False
        if related_type == "evaluation":
            return can_see("meal.view", prog)
        return can_see("programmes.view", prog)
    return False


def parent_editable(related_type, related_id):
    model = _related_model(related_type)
    obj = db.session.get(model, related_id) if model else None
    if obj is None or obj.organization_id != g.tenant.id:
        return False
    if related_type == "staff":
        return can("staff.manage") and obj.status != "exited"
    if related_type in ("programme", "project", "activity", "evaluation", "deliverable", "issue"):
        from app.programme_logic import can_do
        prog = _programme_of(related_type, obj)
        if prog is None:
            return False
        if related_type == "evaluation":
            return can_do("meal.edit", prog)
        if related_type in ("activity", "deliverable") and obj.responsible_id == current_user.id:
            return prog.status not in ("closed", "cancelled") and g.get("support_request") is None
        return can_do("programmes.edit", prog) or (related_type == "activity" and can_do("meal.collect", prog))
    if related_type == "task":
        from app.blueprints.tasks import _archived
        if _archived(obj):
            return False
    return parent_visible(related_type, related_id)


def can_view(doc):
    if not can("documents.view"):
        return False
    if can("documents.manage") or doc.owner_id == current_user.id:
        return True
    if doc.related_type:
        return parent_visible(doc.related_type, doc.related_id)
    if doc.status not in ("approved", "archived"):
        return doc.status == "pending_approval" and can("documents.approve")
    if doc.visibility == Document.VIS_ORG:
        return True
    if doc.visibility == Document.VIS_DEPT:
        return doc.department_id is not None and doc.department_id == my_department_id()
    return any(s.user_id == current_user.id for s in doc.shares)


def can_edit(doc):
    return doc.owner_id == current_user.id or can("documents.manage") or (
        doc.related_type and parent_editable(doc.related_type, doc.related_id))


def visible_stmt():
    """Library listing: standalone documents the person may see."""
    stmt = select(Document).where(Document.organization_id == g.tenant.id, Document.related_type.is_(None))
    if can("documents.manage"):
        return stmt
    me = current_user.id
    shared = exists().where(DocumentShare.document_id == Document.id, DocumentShare.user_id == me)
    published = Document.status.in_(("approved", "archived"))
    dept = my_department_id()
    conds = [Document.owner_id == me,
             published & (Document.visibility == Document.VIS_ORG),
             published & (Document.visibility == Document.VIS_RESTRICTED) & shared]
    if dept:
        conds.append(published & (Document.visibility == Document.VIS_DEPT) & (Document.department_id == dept))
    if can("documents.approve"):
        conds.append(Document.status == "pending_approval")
    return stmt.where(or_(*conds))


def storage_used_bytes(org_id):
    return db.session.scalar(select(func.coalesce(func.sum(DocumentVersion.size_bytes), 0))
                             .where(DocumentVersion.organization_id == org_id)) or 0


def _check_quota(size):
    sub = g.tenant.subscription
    if sub and sub.plan and sub.plan.max_storage_mb:
        limit = sub.plan.max_storage_mb * 1024 * 1024
        if storage_used_bytes(g.tenant.id) + size > limit:
            raise UploadRejected(f"Your plan's storage limit ({sub.plan.max_storage_mb} MB) would be exceeded.")


def store_version(doc, file_storage, note=None):
    """Validate, store and record a new version of ``doc``. Raises UploadRejected."""
    info = inspect_upload(file_storage)
    _check_quota(info["size"])
    key = new_key(g.tenant.id)
    try:
        get_storage().put(key, info["data"], info["mime"])
    except Exception as exc:  # storage outage must not leave a half-written record
        from flask import current_app
        current_app.logger.exception("File storage failed (STORAGE_BACKEND=%s, UPLOAD_ROOT=%s): %s",
                                     current_app.config.get("STORAGE_BACKEND"), current_app.config.get("UPLOAD_ROOT"), exc)
        raise UploadRejected("The file could not be stored. Please try again later.") from exc
    number = (db.session.scalar(select(func.max(DocumentVersion.version_no))
                                .where(DocumentVersion.document_id == doc.id)) or 0) + 1
    v = DocumentVersion(organization_id=g.tenant.id, document_id=doc.id, version_no=number, storage_key=key,
                        filename=info["filename"], mime_type=info["mime"], size_bytes=info["size"],
                        sha256=info["sha256"], note=note, uploaded_by_id=current_user.id)
    db.session.add(v)
    db.session.flush()
    return v


def create_attachment(related_type, related_id, file_storage, title=None):
    """Attach a file to another record (letter, meeting, task, staff file)."""
    doc = Document(organization_id=g.tenant.id, title=(title or getattr(file_storage, "filename", "Attachment"))[:250],
                   owner_id=current_user.id, status="approved", visibility=Document.VIS_RESTRICTED,
                   related_type=related_type, related_id=related_id)
    db.session.add(doc)
    db.session.flush()
    store_version(doc, file_storage)
    return doc


def attachments_for(related_type, related_id):
    return (Document.query.filter_by(organization_id=g.tenant.id, related_type=related_type, related_id=related_id)
            .order_by(Document.created_at).all())


def _approver_ids():
    from app.models import Membership
    from app.rbac import permissions_for_role
    return [m.user_id for m in Membership.query.filter_by(organization_id=g.tenant.id, status=Membership.ACTIVE)
            if m.role and "documents.approve" in permissions_for_role(m.role)]


def _setup_form(form):
    form.folder_id.choices = [(0, "— No folder —")] + _folder_choices()
    form.category_id.choices = [(0, "— None —")] + [(c.id, c.name + (" (needs approval)" if c.requires_approval else ""))
                                                     for c in DocumentCategory.query.filter_by(organization_id=g.tenant.id)
                                                     .order_by(DocumentCategory.name)]
    form.department_id.choices = department_choices()
    form.shared_with.choices = [(uid, name) for uid, name in member_choices() if uid != current_user.id]


def _folder_choices():
    folders = DocumentFolder.query.filter_by(organization_id=g.tenant.id).all()
    by_id = {f.id: f for f in folders}

    def path(f):
        parts, seen = [], set()
        while f is not None and f.id not in seen:
            seen.add(f.id)
            parts.append(f.name)
            f = by_id.get(f.parent_id)
        return " / ".join(reversed(parts))
    return sorted(((f.id, path(f)) for f in folders), key=lambda x: x[1].lower())


def _apply_fields(doc, form):
    for f in ("title", "description", "visibility", "expiry_date"):
        setattr(doc, f, getattr(form, f).data or None)
    doc.visibility = form.visibility.data
    doc.folder_id = tenant_get_or_404(DocumentFolder, form.folder_id.data).id if form.folder_id.data else None
    doc.category_id = tenant_get_or_404(DocumentCategory, form.category_id.data).id if form.category_id.data else None
    if form.department_id.data:
        tenant_get_or_404(Department, form.department_id.data)
    doc.department_id = form.department_id.data or (my_department_id() if doc.visibility == Document.VIS_DEPT else None)
    if doc.visibility == Document.VIS_DEPT and not doc.department_id:
        raise UploadRejected("Choose the department that may see this document.")
    wanted = set(form.shared_with.data or []) if doc.visibility == Document.VIS_RESTRICTED else set()
    for s in list(doc.shares):
        if s.user_id not in wanted:
            doc.shares.remove(s)
    have = {s.user_id for s in doc.shares}
    for uid in wanted - have:
        doc.shares.append(DocumentShare(organization_id=g.tenant.id, user_id=uid))
    return wanted - have


def _needs_approval(doc, form):
    return bool(form.submit_for_approval.data or (doc.category and doc.category.requires_approval))


# --- Library ------------------------------------------------------------------------------

@bp.route("/")
@require_permission("documents.view")
def index():
    folder_id = request.args.get("folder", type=int)
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    category = request.args.get("category", type=int)
    stmt = visible_stmt()
    folder = tenant_get_or_404(DocumentFolder, folder_id) if folder_id else None
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.description.ilike(like)))
    elif folder is not None:
        stmt = stmt.where(Document.folder_id == folder.id)
    if status in Document.STATUSES:
        stmt = stmt.where(Document.status == status)
    elif not q:
        stmt = stmt.where(Document.status != "archived")
    if category:
        stmt = stmt.where(Document.category_id == category)
    page = db.paginate(stmt.order_by(Document.updated_at.desc()), page=page_arg(), per_page=25, error_out=False)
    subfolders = [] if q else (DocumentFolder.query.filter_by(organization_id=g.tenant.id,
                                                             parent_id=folder.id if folder else None)
                               .order_by(DocumentFolder.name).all())
    crumbs = []
    f = folder
    while f is not None:
        crumbs.insert(0, f)
        f = f.parent
    categories = DocumentCategory.query.filter_by(organization_id=g.tenant.id).order_by(DocumentCategory.name).all()
    used = storage_used_bytes(g.tenant.id) if can("documents.manage") else None
    return render_template("documents/index.html", page=page, folder=folder, subfolders=subfolders, crumbs=crumbs,
                           q=q, status=status, category=category, categories=categories, used=used)


@bp.route("/upload", methods=["GET", "POST"])
@require_permission("documents.upload")
def upload():
    form = UploadForm()
    _setup_form(form)
    rel_type = request.values.get("related_type") or None
    rel_id = request.values.get("related_id", type=int)
    if rel_type and (rel_type not in RELATED or not rel_id or not parent_editable(rel_type, rel_id)):
        abort(403)
    if request.method == "GET":
        form.folder_id.data = request.args.get("folder", type=int)
        form.department_id.data = my_department_id()
    if rel_type:
        # Attachments take the visibility of the record they belong to; the form does not ask for it, so the
        # choice must not be required (before this, every attachment was refused without a visible message).
        form.visibility.choices = list(Document.VISIBILITY.items())
        form.visibility.validate_choice = False
        if not form.visibility.data:
            form.visibility.data = Document.VIS_RESTRICTED
    if form.validate_on_submit():
        doc = Document(organization_id=g.tenant.id, owner_id=current_user.id, related_type=rel_type, related_id=rel_id)
        try:
            with db.session.no_autoflush:
                new_shares = _apply_fields(doc, form)
            db.session.add(doc)
            db.session.flush()
            store_version(doc, form.file.data)
        except UploadRejected as exc:
            db.session.rollback()
            form.file.errors.append(str(exc))
        else:
            if rel_type:
                doc.status, doc.visibility = "approved", Document.VIS_RESTRICTED
            elif _needs_approval(doc, form):
                doc.status = "pending_approval"
                notify(_approver_ids(), "document", f"Document awaiting approval: {doc.title}",
                       f"Uploaded by {current_user.full_name}", "documents.detail", doc_id=doc.id)
            else:
                doc.status = "approved"
            if doc.status == "approved" and new_shares:
                notify(new_shares, "document", f"{current_user.full_name} shared a document with you", doc.title,
                       "documents.detail", doc_id=doc.id)
            audit.record("document.uploaded", f"Document '{doc.title}' uploaded", entity=doc)
            db.session.commit()
            flash("Document uploaded.", "success")
            if rel_type:
                return redirect(_parent_url(rel_type, rel_id))
            return redirect(url_for("documents.detail", doc_id=doc.id))
    return render_template("documents/upload.html", form=form, related_type=rel_type, related_id=rel_id,
                           back_url=_parent_url(rel_type, rel_id) if rel_type else None)


def _parent_url(rel_type, rel_id):
    return {"staff": lambda: url_for("staff.detail", staff_id=rel_id) + "#documents",
            "correspondence": lambda: url_for("correspondence.detail", item_id=rel_id),
            "meeting": lambda: url_for("meetings.detail", meeting_id=rel_id),
            "task": lambda: url_for("tasks.detail", task_id=rel_id),
            "programme": lambda: url_for("programmes.overview", pid=rel_id) + "#documents",
            "project": lambda: url_for("projects.overview", pid=rel_id) + "#documents",
            "activity": lambda: _owner_url(db.session.get(Activity, rel_id), "activity_detail", aid=rel_id),
            "evaluation": lambda: _owner_url(db.session.get(Evaluation, rel_id), "evaluation_edit", eid=rel_id),
            "deliverable": lambda: _owner_url(db.session.get(_related_model("deliverable"), rel_id), "deliverables") + "#d" + str(rel_id),
            "issue": lambda: _owner_url(db.session.get(_related_model("issue"), rel_id), "risks") + "#issues"}[rel_type]()


def _owner_url(obj, endpoint, **kw):
    from app.programme_logic import owner_of
    owner = owner_of(obj)
    return url_for(f"{owner.perm}.{endpoint}", pid=owner.id, **kw)


@bp.route("/<int:doc_id>")
@require_permission("documents.view")
def detail(doc_id):
    doc = tenant_get_or_404(Document, doc_id)
    if not can_view(doc):
        abort(404)
    editable = can_edit(doc) and g.get("support_request") is None
    logs = []
    if editable:
        logs = (DocumentAccessLog.query.filter_by(document_id=doc.id)
                .order_by(DocumentAccessLog.created_at.desc()).limit(30).all())
    form = None
    if editable and not doc.related_type:
        form = DocumentForm(obj=doc)
        _setup_form(form)
        if request.method == "GET":
            form.shared_with.data = [s.user_id for s in doc.shares]
    return render_template("documents/detail.html", doc=doc, editable=editable, logs=logs, form=form,
                           version_form=VersionForm(), decision_form=DecisionForm(), action_form=ActionForm(),
                           can_approve=can("documents.approve") and doc.owner_id != current_user.id,
                           parent_url=_parent_url(doc.related_type, doc.related_id) if doc.related_type else None)


@bp.route("/<int:doc_id>/download")
@require_permission("documents.view")
def download(doc_id):
    doc = tenant_get_or_404(Document, doc_id)
    if not can_view(doc):
        abort(404)
    vno = request.args.get("v", type=int)
    version = next((v for v in doc.versions if v.version_no == vno), None) if vno else doc.current
    if version is None:
        abort(404)
    try:
        data = get_storage().get(version.storage_key)
    except StorageError:
        abort(410)
    db.session.add(DocumentAccessLog(organization_id=g.tenant.id, document_id=doc.id, version_id=version.id,
                                     user_id=current_user.id, via_support_access=g.get("support_request") is not None))
    db.session.commit()
    resp = Response(data, mimetype=version.mime_type)
    inline = request.args.get("inline") == "1" and version.mime_type in ("application/pdf", "image/png", "image/jpeg",
                                                                          "image/webp", "image/gif")
    from urllib.parse import quote
    disp = "inline" if inline else "attachment"
    resp.headers["Content-Disposition"] = f"{disp}; filename*=UTF-8''{quote(version.filename)}"
    resp.headers["Cache-Control"] = "private, no-store"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return resp


@bp.route("/<int:doc_id>/edit", methods=["POST"])
@require_permission("documents.view")
def edit(doc_id):
    doc = tenant_get_or_404(Document, doc_id)
    if not can_view(doc) or not can_edit(doc) or doc.related_type:
        abort(403)
    form = DocumentForm()
    _setup_form(form)
    if form.validate_on_submit():
        try:
            new_shares = _apply_fields(doc, form)
        except UploadRejected as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("documents.detail", doc_id=doc.id))
        if doc.status in ("rejected",) and _needs_approval(doc, form):
            doc.status = "pending_approval"
            notify(_approver_ids(), "document", f"Document awaiting approval: {doc.title}", None,
                   "documents.detail", doc_id=doc.id)
        if new_shares and doc.status == "approved":
            notify(new_shares, "document", f"{current_user.full_name} shared a document with you", doc.title,
                   "documents.detail", doc_id=doc.id)
        audit.record("document.updated", f"Document '{doc.title}' details updated", entity=doc)
        db.session.commit()
        flash("Document updated.", "success")
    else:
        flash("Check the document details.", "danger")
    return redirect(url_for("documents.detail", doc_id=doc.id))


@bp.route("/<int:doc_id>/version", methods=["POST"])
@require_permission("documents.upload")
def new_version(doc_id):
    doc = tenant_get_or_404(Document, doc_id)
    if not can_view(doc) or not can_edit(doc) or doc.status == "archived":
        abort(403)
    form = VersionForm()
    if form.validate_on_submit():
        try:
            v = store_version(doc, form.file.data, form.note.data or None)
        except UploadRejected as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            needs = doc.category and doc.category.requires_approval and not doc.related_type
            if needs:
                doc.status = "pending_approval"
                notify(_approver_ids(), "document", f"New version awaiting approval: {doc.title}", None,
                       "documents.detail", doc_id=doc.id)
            doc.updated_at = utcnow()
            audit.record("document.version_added", f"Version {v.version_no} of '{doc.title}' uploaded", entity=doc)
            db.session.commit()
            flash(f"Version {v.version_no} uploaded.", "success")
    return redirect(url_for("documents.detail", doc_id=doc.id))


@bp.route("/<int:doc_id>/<action>", methods=["POST"])
@require_permission("documents.view")
def act(doc_id, action):
    doc = tenant_get_or_404(Document, doc_id)
    if not can_view(doc):
        abort(404)
    form = DecisionForm()
    if not form.validate_on_submit():
        abort(400)
    if action in ("approve", "reject"):
        if not can("documents.approve") or doc.owner_id == current_user.id or doc.status != "pending_approval":
            abort(403)
        doc.status = "approved" if action == "approve" else "rejected"
        doc.approved_by_id, doc.approved_at, doc.decision_note = current_user.id, utcnow(), form.note.data or None
        notify([doc.owner_id], "document", f"Your document was {doc.status}: {doc.title}", doc.decision_note,
               "documents.detail", doc_id=doc.id)
        if doc.status == "approved":
            notify([s.user_id for s in doc.shares], "document", f"A document was shared with you: {doc.title}", None,
                   "documents.detail", doc_id=doc.id)
    elif action == "submit":
        if doc.owner_id != current_user.id or doc.status not in ("rejected", "approved"):
            abort(403)
        doc.status = "pending_approval"
        notify(_approver_ids(), "document", f"Document awaiting approval: {doc.title}", None,
               "documents.detail", doc_id=doc.id)
    elif action in ("archive", "restore"):
        if not can_edit(doc):
            abort(403)
        if action == "archive" and doc.status == "approved":
            doc.status = "archived"
        elif action == "restore" and doc.status == "archived":
            doc.status = "approved"
        else:
            abort(400)
    elif action == "delete":
        if not (can("documents.manage") or (doc.related_type and can_edit(doc))):
            abort(403)
        title, parent = doc.title, (doc.related_type, doc.related_id)
        keys = [v.storage_key for v in doc.versions]
        audit.record("document.deleted", f"Document '{title}' deleted ({len(keys)} versions)", entity=doc)
        db.session.delete(doc)
        db.session.commit()
        for k in keys:
            try:
                get_storage().delete(k)
            except Exception:  # pragma: no cover - orphaned files are harmless and logged
                pass
        flash(f"'{title}' deleted.", "success")
        if parent[0]:
            return redirect(_parent_url(*parent))
        return redirect(url_for("documents.index"))
    else:
        abort(404)
    audit.record(f"document.{action}", f"Document '{doc.title}': {action}", entity=doc)
    db.session.commit()
    flash("Done.", "success")
    return redirect(url_for("documents.detail", doc_id=doc.id))


# --- Folders & categories -----------------------------------------------------------------

@bp.route("/organize", methods=["GET", "POST"])
@require_permission("documents.manage")
def organize():
    folder_form, cat_form = FolderForm(prefix="f"), CategoryForm(prefix="c")
    folder_form.parent_id.choices = [(0, "— Top level —")] + _folder_choices()
    if request.method == "POST" and request.form.get("what") == "folder" and folder_form.validate_on_submit():
        parent = tenant_get_or_404(DocumentFolder, folder_form.parent_id.data) if folder_form.parent_id.data else None
        if DocumentFolder.query.filter_by(organization_id=g.tenant.id, parent_id=parent.id if parent else None,
                                          name=folder_form.name.data).first():
            folder_form.name.errors.append("A folder with this name already exists there.")
        else:
            db.session.add(DocumentFolder(organization_id=g.tenant.id, name=folder_form.name.data,
                                          parent_id=parent.id if parent else None))
            audit.record("document.folder_created", f"Folder {folder_form.name.data} created")
            db.session.commit()
            flash("Folder created.", "success")
            return redirect(url_for("documents.organize"))
    if request.method == "POST" and request.form.get("what") == "category" and cat_form.validate_on_submit():
        if DocumentCategory.query.filter_by(organization_id=g.tenant.id, name=cat_form.name.data).first():
            cat_form.name.errors.append("This category already exists.")
        else:
            db.session.add(DocumentCategory(organization_id=g.tenant.id, name=cat_form.name.data,
                                            requires_approval=cat_form.requires_approval.data))
            audit.record("document.category_created", f"Category {cat_form.name.data} created")
            db.session.commit()
            flash("Category created.", "success")
            return redirect(url_for("documents.organize"))
    folders = _folder_choices()
    counts = dict(db.session.execute(select(Document.folder_id, func.count()).where(
        Document.organization_id == g.tenant.id).group_by(Document.folder_id)).all())
    child = {f.parent_id for f in DocumentFolder.query.filter_by(organization_id=g.tenant.id)}
    cats = DocumentCategory.query.filter_by(organization_id=g.tenant.id).order_by(DocumentCategory.name).all()
    return render_template("documents/organize.html", folder_form=folder_form, cat_form=cat_form, folders=folders,
                           counts=counts, child=child, cats=cats, action_form=ActionForm())


@bp.route("/folders/<int:folder_id>/delete", methods=["POST"])
@require_permission("documents.manage")
def delete_folder(folder_id):
    folder = tenant_get_or_404(DocumentFolder, folder_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    if Document.query.filter_by(folder_id=folder.id).count() or DocumentFolder.query.filter_by(parent_id=folder.id).count():
        flash("Only empty folders can be deleted.", "danger")
    else:
        audit.record("document.folder_deleted", f"Folder {folder.name} deleted")
        db.session.delete(folder)
        db.session.commit()
        flash("Folder deleted.", "success")
    return redirect(url_for("documents.organize"))


@bp.route("/categories/<int:cat_id>/toggle", methods=["POST"])
@require_permission("documents.manage")
def toggle_category(cat_id):
    cat = tenant_get_or_404(DocumentCategory, cat_id)
    if ActionForm().validate_on_submit():
        cat.requires_approval = not cat.requires_approval
        audit.record("document.category_updated", f"Category {cat.name}: approval {'required' if cat.requires_approval else 'not required'}")
        db.session.commit()
    return redirect(url_for("documents.organize"))

