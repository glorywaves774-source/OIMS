"""Phase 9: encrypted backups and restore."""
import io
import os
from datetime import date

import pytest

from app import backup as bk
from app.extensions import db as _db
from tests.conftest import PDF, login, make_department, make_org, make_staff_profile

KEY = bk.new_key()


@pytest.fixture
def keyed(app, tmp_path):
    app.config.update(BACKUP_ENCRYPTION_KEY=KEY, BACKUP_DIR=str(tmp_path / "backups"), BACKUP_S3_BUCKET=None)
    yield app
    app.config.update(BACKUP_ENCRYPTION_KEY=None, BACKUP_DIR=None)


def _enc(data, key=KEY):
    out = io.BytesIO()
    bk.encrypt_stream(io.BytesIO(data), out, bk.base64.urlsafe_b64decode(key))
    return out.getvalue()


def _dec(data, key=KEY):
    out = io.BytesIO()
    bk.decrypt_stream(io.BytesIO(data), out, bk.base64.urlsafe_b64decode(key))
    return out.getvalue()


@pytest.mark.parametrize("size", [0, 1, bk.CHUNK - 1, bk.CHUNK, bk.CHUNK + 1, 3 * bk.CHUNK + 7])
def test_encryption_round_trip(size):
    data = os.urandom(size)
    enc = _enc(data)
    if size >= 64:   # the original bytes do not appear in the encrypted file
        assert data[:64] not in enc
    assert _dec(enc) == data


def test_damaged_cut_off_or_wrong_key_is_refused():
    data = os.urandom(2 * bk.CHUNK + 10)
    enc = _enc(data)
    flipped = bytearray(enc)
    flipped[len(enc) // 2] ^= 1
    for bad in (bytes(flipped), enc[:-5], enc[: len(bk.MAGIC) + 4 + 12 + bk.CHUNK + 16], enc + b"x", b"junk"):
        with pytest.raises(bk.BackupError):
            _dec(bad)
    with pytest.raises(bk.BackupError, match="wrong BACKUP_ENCRYPTION_KEY"):
        _dec(enc, bk.new_key())


def test_missing_or_invalid_key_and_destination(keyed):
    keyed.config["BACKUP_ENCRYPTION_KEY"] = None
    with pytest.raises(bk.BackupError, match="BACKUP_ENCRYPTION_KEY is not set"):
        bk._key()
    keyed.config["BACKUP_ENCRYPTION_KEY"] = "short"
    with pytest.raises(bk.BackupError):
        bk._key()
    keyed.config.update(BACKUP_DIR=None)
    with pytest.raises(bk.BackupError, match="No backup destination"):
        bk.get_target()
    keyed.config.update(BACKUP_S3_BUCKET="docs", S3_BUCKET="docs", BACKUP_S3_PREFIX="")
    with pytest.raises(bk.BackupError, match="separate bucket"):
        bk.get_target()
    keyed.config.update(BACKUP_S3_BUCKET=None, S3_BUCKET=None)


def test_old_backups_are_thinned(keyed, tmp_path):
    target = bk.DirTarget(str(tmp_path / "t"))
    src = tmp_path / "x"
    src.write_bytes(b"x")
    names = []
    for y, m, d in [(2025, 9, 1), (2025, 9, 15), (2025, 10, 1), (2025, 10, 2), (2026, 10, 30), (2026, 11, 1),
                    (2026, 11, 2), (2026, 11, 10), (2026, 11, 15)]:
        n = f"zentava-{y}{m:02d}{d:02d}-020000.ztvbak"
        target.put_file(f"db/{n}", str(src))
        names.append(n)
    bk.prune(target, log=lambda *_: None, today=date(2026, 11, 16))
    kept = bk.list_backups(target)
    # the last 14 days (3 Nov onwards), plus the first backup of each month from Dec 2025 to Nov 2026
    assert kept == ["zentava-20261030-020000.ztvbak", "zentava-20261101-020000.ztvbak",
                    "zentava-20261110-020000.ztvbak", "zentava-20261115-020000.ztvbak"]


def test_backup_needs_postgres(keyed):
    if _db.engine.dialect.name == "postgresql":
        pytest.skip("covered by the round trip")
    with pytest.raises(bk.BackupError, match="PostgreSQL"):
        bk.create_backup(log=lambda *_: None)


def test_backup_and_restore_round_trip(keyed, client, tmp_path):
    """Back up, wipe, restore into the empty database: every row, link and file comes back."""
    if _db.engine.dialect.name != "postgresql":
        pytest.skip("needs PostgreSQL (set TEST_DATABASE_URL)")
    from flask_migrate import stamp
    from sqlalchemy import text
    from app.crypto import encrypt_text
    from app.models import Beneficiary, Department, Household, Task
    from app.storage import get_storage
    from app.tenancy import clear_tenant, set_tenant

    org, admin = make_org("Backup Trust", admin_email="admin@backup.org")
    set_tenant(org.id)
    dept = make_department(org, "Programmes")
    head = make_staff_profile(org, admin, department=dept)
    dept.head_staff_id = head.id                      # departments <-> staff profiles link both ways
    hh = Household(organization_id=org.id, code="HH-1", name="Mensah household")
    _db.session.add(hh); _db.session.flush()
    b = Beneficiary(organization_id=org.id, code="BEN-1", first_name="Ama", last_name="Mensah", sex="female",
                    household_id=hh.id, phone_enc=encrypt_text("0244 000 111"),
                    notes="Line one\nLine two, with a comma\nand \"quotes\"")
    _db.session.add(b); _db.session.flush()
    hh.head_id = b.id                                 # households <-> beneficiaries link both ways
    parent = Task(organization_id=org.id, title="Parent task")
    _db.session.add(parent); _db.session.flush()
    _db.session.add(Task(organization_id=org.id, title="Child task", parent_id=parent.id))
    _db.session.commit()
    clear_tenant()
    login(client, "admin@backup.org")
    r = client.post(f"/o/{org.slug}/documents/upload", content_type="multipart/form-data",
                    data={"title": "Board minutes", "visibility": "organization",
                          "file": (io.BytesIO(PDF), "minutes.pdf")})
    assert r.status_code == 302
    stamp()                                           # the test database is built without migrations

    def snapshot():
        out = {}
        for t in sorted(_db.metadata.tables):
            out[t] = _db.session.execute(text(
                f'select count(*), md5(coalesce(string_agg(to_jsonb(s)::text, \'|\' order by to_jsonb(s)::text), \'\')) '
                f'from "{t}" s')).one()
        return out

    ids = {"hh": hh.id, "b": b.id, "dept": dept.id, "head": head.id, "parent": parent.id}
    before = snapshot()
    name = bk.create_backup(log=lambda *_: None)
    assert bk.list_backups() == [name]
    assert bk.verify_backup(name, log=lambda *_: None)["tables"]["beneficiaries"]["rows"] == 1
    store = get_storage()
    key = _db.session.execute(text("select storage_key from document_versions")).scalar()

    # Refuses a database that has data
    with pytest.raises(bk.BackupError, match="already has data"):
        bk.restore_backup(name, log=lambda *_: None)

    # Disaster: everything is gone (database and files)
    _db.session.remove()
    _db.drop_all()
    _db.session.execute(text("drop table if exists alembic_version"))
    _db.session.commit()
    store.delete(key)
    bk.restore_backup(name, log=lambda *_: None)
    assert snapshot() == before
    assert store.get(key) == PDF
    # Links that point both ways are back, and new records get fresh ids
    assert _db.session.get(Household, ids["hh"]).head_id == ids["b"]
    assert _db.session.get(Beneficiary, ids["b"]).household_id == ids["hh"]
    assert _db.session.get(Department, ids["dept"]).head_staff_id == ids["head"]
    org_id, slug = _db.session.execute(text("select id, slug from organizations")).one()
    set_tenant(org_id)
    t = Task(organization_id=org_id, title="After restore")
    _db.session.add(t); _db.session.commit()
    assert t.id > ids["parent"] + 1
    clear_tenant()
    # The restored workspace works: sign in and open it
    login(client, "admin@backup.org")
    assert client.get(f"/o/{slug}/").status_code == 200
