"""Phase 2: documents, storage and file validation."""
import io
import os
import zipfile

import pytest

from app.models import (Document, DocumentAccessLog, DocumentCategory, DocumentVersion, Notification, Subscription,
                        SubscriptionPlan, Task)
from tests.conftest import PDF, add_member, login, logout, make_department, make_org, make_staff_profile


@pytest.fixture
def org(app):
    o, admin = make_org("Doc Org", admin_email="admin@doc.org")
    prog, fin = make_department(o, "Programmes"), make_department(o, "Finance")
    ppl = {"org": o, "prog": prog, "fin": fin}
    for key, role, dept in [("ama", "Staff Member", prog), ("kofi", "Staff Member", fin), ("esi", "Staff Member", prog),
                            ("rec", "Records Officer", None), ("hr", "HR Officer", None)]:
        u, _ = add_member(o, f"{key}@doc.org", role_name=role)
        ppl[key] = u
        ppl[key + "_staff"] = make_staff_profile(o, u, department=dept)
    return ppl


def up(client, o, title="Plan", data=PDF, name="plan.pdf", **extra):
    payload = {"title": title, "visibility": "organization", "file": (io.BytesIO(data), name)}
    payload.update(extra)
    return client.post(f"/o/{o.slug}/documents/upload", data=payload, content_type="multipart/form-data")


def docx_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def test_upload_download_and_access_log(client, app, org):
    o = org["org"]
    login(client, "ama@doc.org")
    assert up(client, o).status_code == 302
    doc = Document.query.one()
    v = doc.current
    assert v.version_no == 1 and v.size_bytes == len(PDF) and v.mime_type == "application/pdf"
    assert v.storage_key.startswith(f"org-{o.id}/") and "plan" not in v.storage_key
    assert os.path.exists(os.path.join(app.config["UPLOAD_ROOT"], v.storage_key))
    r = client.get(f"/o/{o.slug}/documents/{doc.id}/download")
    assert r.data == PDF and "attachment" in r.headers["Content-Disposition"]
    assert "sandbox" in r.headers["Content-Security-Policy"]
    assert DocumentAccessLog.query.filter_by(document_id=doc.id).count() == 1


@pytest.mark.parametrize("data,name,msg", [
    (b"MZ\x90\x00 fake exe", "virus.exe", b"not allowed"),
    (b"MZ\x90\x00 pretending", "report.pdf", b"does not match"),
    (b"PK\x03\x04 not really", "sheet.xlsx", b"does not match"),
    (b"", "empty.pdf", b"empty"),
    (b"<svg onload=alert(1)>", "img.svg", b"not allowed"),
])
def test_upload_rejects_bad_files(client, org, data, name, msg):
    login(client, "ama@doc.org")
    r = up(client, org["org"], data=data, name=name)
    assert msg in r.data and Document.query.count() == 0


def test_office_formats_accepted(client, org):
    login(client, "ama@doc.org")
    assert up(client, org["org"], data=docx_bytes(), name="letter.docx").status_code == 302
    assert up(client, org["org"], title="CSV", data=b"a,b\n1,2\n", name="data.csv").status_code == 302


def test_visibility_rules(client, org):
    o = org["org"]
    login(client, "ama@doc.org")
    up(client, o, title="Everyone doc")
    up(client, o, title="Dept doc", visibility="department", department_id=org["prog"].id)
    up(client, o, title="Shared doc", visibility="restricted", shared_with=[org["kofi"].id])
    ids = {d.title: d.id for d in Document.query.all()}
    logout(client)

    login(client, "esi@doc.org")  # same department, not shared
    listing = client.get(f"/o/{o.slug}/documents/").data
    assert b"Everyone doc" in listing and b"Dept doc" in listing and b"Shared doc" not in listing
    assert client.get(f"/o/{o.slug}/documents/{ids['Shared doc']}").status_code == 404
    assert client.get(f"/o/{o.slug}/documents/{ids['Shared doc']}/download").status_code == 404
    logout(client)

    login(client, "kofi@doc.org")  # other department, shared with
    listing = client.get(f"/o/{o.slug}/documents/").data
    assert b"Dept doc" not in listing and b"Shared doc" in listing
    assert client.get(f"/o/{o.slug}/documents/{ids['Dept doc']}").status_code == 404
    assert Notification.query.filter_by(user_id=org["kofi"].id, kind="document").count() == 1
    logout(client)

    login(client, "rec@doc.org")  # documents.manage sees all
    assert client.get(f"/o/{o.slug}/documents/{ids['Shared doc']}").status_code == 200


def test_approval_workflow(client, org, db):
    o = org["org"]
    cat = DocumentCategory.query.filter_by(organization_id=o.id, name="Policies & procedures").one()
    login(client, "ama@doc.org")
    up(client, o, title="Travel policy", category_id=cat.id)
    doc = Document.query.one()
    assert doc.status == "pending_approval"
    assert Notification.query.filter_by(user_id=org["rec"].id, kind="document").count() == 1
    assert client.post(f"/o/{o.slug}/documents/{doc.id}/approve", data={}).status_code == 403  # not own
    logout(client)
    login(client, "esi@doc.org")
    assert b"Travel policy" not in client.get(f"/o/{o.slug}/documents/").data
    logout(client)
    login(client, "rec@doc.org")
    client.post(f"/o/{o.slug}/documents/{doc.id}/approve", data={"note": "OK"})
    db.session.expire_all()
    assert db.session.get(Document, doc.id).status == "approved"
    logout(client)
    login(client, "esi@doc.org")
    assert b"Travel policy" in client.get(f"/o/{o.slug}/documents/").data


def test_versions(client, org, db):
    o = org["org"]
    login(client, "ama@doc.org")
    up(client, o)
    doc = Document.query.one()
    v2 = PDF.replace(b"1.4", b"1.7")
    client.post(f"/o/{o.slug}/documents/{doc.id}/version", data={"file": (io.BytesIO(v2), "plan-v2.pdf"),
                                                                  "note": "Updated budget"},
                content_type="multipart/form-data")
    assert DocumentVersion.query.filter_by(document_id=doc.id).count() == 2
    assert client.get(f"/o/{o.slug}/documents/{doc.id}/download").data == v2
    assert client.get(f"/o/{o.slug}/documents/{doc.id}/download?v=1").data == PDF
    logout(client)
    login(client, "esi@doc.org")  # can view, not edit
    r = client.post(f"/o/{o.slug}/documents/{doc.id}/version", data={"file": (io.BytesIO(PDF), "x.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 403


def test_storage_quota(client, org, db):
    o = org["org"]
    plan = SubscriptionPlan(code="micro", name="Micro", max_storage_mb=1)
    db.session.add(plan)
    db.session.flush()
    db.session.add(Subscription(organization_id=o.id, plan_id=plan.id, status="active"))
    db.session.commit()
    login(client, "ama@doc.org")
    big = PDF + b"0" * (1024 * 1024)
    r = up(client, o, data=big)
    assert b"storage limit" in r.data and Document.query.count() == 0


def test_task_attachment_follows_task_visibility(client, org, db):
    o = org["org"]
    t = Task(organization_id=o.id, title="Budget", assigned_to_id=org["ama"].id, created_by_id=org["ama"].id)
    db.session.add(t)
    db.session.commit()
    login(client, "ama@doc.org")
    r = client.post(f"/o/{o.slug}/documents/upload", data={"title": "Budget sheet", "visibility": "organization",
                                                           "related_type": "task", "related_id": t.id,
                                                           "file": (io.BytesIO(b"a,b\n"), "b.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 302 and f"/tasks/{t.id}" in r.headers["Location"]
    doc = Document.query.one()
    assert doc.related_type == "task"
    logout(client)
    login(client, "kofi@doc.org")
    assert client.get(f"/o/{o.slug}/documents/{doc.id}/download").status_code == 404
    assert b"Budget sheet" not in client.get(f"/o/{o.slug}/documents/").data
    # cannot attach to a task they cannot see
    r = client.post(f"/o/{o.slug}/documents/upload", data={"title": "x", "visibility": "organization",
                                                           "related_type": "task", "related_id": t.id,
                                                           "file": (io.BytesIO(PDF), "x.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 403


def test_staff_documents_need_hr_records_access(client, org):
    o = org["org"]
    login(client, "hr@doc.org")
    r = client.post(f"/o/{o.slug}/documents/upload", data={"title": "Contract", "visibility": "organization",
                                                           "related_type": "staff", "related_id": org["kofi_staff"].id,
                                                           "file": (io.BytesIO(PDF), "contract.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    doc = Document.query.one()
    logout(client)
    login(client, "ama@doc.org")
    assert client.get(f"/o/{o.slug}/documents/{doc.id}").status_code == 404
    logout(client)
    login(client, "kofi@doc.org")  # the staff member's own file
    assert client.get(f"/o/{o.slug}/documents/{doc.id}").status_code == 200


def test_delete_removes_files(client, app, org):
    o = org["org"]
    login(client, "rec@doc.org")
    up(client, o)
    doc = Document.query.one()
    path = os.path.join(app.config["UPLOAD_ROOT"], doc.current.storage_key)
    assert os.path.exists(path)
    client.post(f"/o/{o.slug}/documents/{doc.id}/delete", data={})
    assert Document.query.count() == 0 and not os.path.exists(path)


def test_folders_and_categories(client, org):
    o = org["org"]
    login(client, "rec@doc.org")
    client.post(f"/o/{o.slug}/documents/organize", data={"what": "folder", "f-name": "Board papers"})
    from app.models import DocumentFolder
    f = DocumentFolder.query.one()
    up(client, o, title="Minutes Jan", folder_id=f.id)
    assert b"Minutes Jan" in client.get(f"/o/{o.slug}/documents/?folder={f.id}").data
    r = client.post(f"/o/{o.slug}/documents/folders/{f.id}/delete", data={}, follow_redirects=True)
    assert b"Only empty folders" in r.data


def test_cross_tenant_document_access(client, org):
    o = org["org"]
    login(client, "ama@doc.org")
    up(client, o)
    doc = Document.query.one()
    logout(client)
    o2, _ = make_org("Elsewhere", admin_email="admin@else.org")
    login(client, "admin@else.org")
    assert client.get(f"/o/{o2.slug}/documents/{doc.id}").status_code == 404
    assert client.get(f"/o/{o2.slug}/documents/{doc.id}/download").status_code == 404


def test_s3_backend(app, monkeypatch):
    moto = pytest.importorskip("moto")
    import boto3
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with moto.mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="oims-test")
        from app.storage import S3Storage
        s = S3Storage("oims-test", region="us-east-1", access_key="x", secret_key="y", prefix="prod")
        s.put("org-1/abc", b"hello", "text/plain")
        assert s.get("org-1/abc") == b"hello"
        s.delete("org-1/abc")
        from app.storage import StorageError
        with pytest.raises(StorageError):
            s.get("org-1/abc")
        assert s.check()


def test_production_requires_storage_config(monkeypatch):
    from app import create_app
    monkeypatch.setenv("SECRET_KEY", "x" * 40)
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    for k in ("UPLOAD_ROOT", "STORAGE_BACKEND", "S3_BUCKET"):
        monkeypatch.delenv(k, raising=False)
    import importlib

    import app.config as cfg
    importlib.reload(cfg)
    monkeypatch.setattr("app.CONFIGS", cfg.CONFIGS)
    try:
        with pytest.raises(RuntimeError, match="UPLOAD_ROOT"):
            create_app("production")
    finally:
        importlib.reload(cfg)
