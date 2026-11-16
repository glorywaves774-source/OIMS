"""Encrypted off-site backups and restore (PostgreSQL).

What a backup contains
  * ``db/<timestamp>.ztvbak``: every table of the database (PostgreSQL COPY, CSV), with a manifest that
    records the schema revision, row counts and a SHA-256 checksum of each table.
  * ``files/<storage key>.enc``: each uploaded document, copied once (stored files never change: a new
    version gets a new key), so each nightly run only adds new files.

Everything is encrypted before it leaves the server (AES-256-GCM, in 1 MiB pieces; the last piece is
marked, so a cut-off file is detected) with BACKUP_ENCRYPTION_KEY, which is never stored with the backups.

Where backups go: an S3-compatible bucket separate from the documents bucket (BACKUP_S3_*), or a folder
(BACKUP_DIR). Database backups are thinned to the last BACKUP_KEEP_DAILY days plus one per month for
BACKUP_KEEP_MONTHLY months.

Restore loads a backup into an EMPTY database: it brings the schema to the backup's revision, loads every
table (links that point forward or to the same table are filled in afterwards), checks row counts,
resets id counters and then upgrades to the current schema.
"""
import base64
import gzip
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import struct
import tarfile
import tempfile
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app
from sqlalchemy import inspect, text

from app.extensions import db

MAGIC = b"ZTVBAK1\n"
CHUNK = 1024 * 1024
NAME_RE = re.compile(r"^zentava-(\d{8})-(\d{6})\.ztvbak$")


class BackupError(RuntimeError):
    pass


# --- keys and encryption ---------------------------------------------------------------------

def new_key():
    """A fresh random key, printed once by ``flask oims backup-key``."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def _key():
    raw = current_app.config.get("BACKUP_ENCRYPTION_KEY")
    if not raw:
        raise BackupError("BACKUP_ENCRYPTION_KEY is not set. Create one with: flask --app wsgi oims backup-key")
    try:
        key = base64.urlsafe_b64decode(raw.encode())
    except (ValueError, TypeError) as exc:
        raise BackupError("BACKUP_ENCRYPTION_KEY is not a valid key") from exc
    if len(key) != 32:
        raise BackupError("BACKUP_ENCRYPTION_KEY must be 32 bytes (use flask oims backup-key)")
    return key


def encrypt_stream(src, dst, key=None):
    """Encrypt file object src into dst. Each piece: length, nonce, ciphertext; the last piece is marked."""
    aes = AESGCM(key or _key())
    prefix = secrets.token_bytes(4)
    dst.write(MAGIC)
    n = 0
    piece = src.read(CHUNK)
    while True:
        nxt = src.read(CHUNK)
        last = not nxt
        nonce = prefix + struct.pack(">Q", n)
        ct = aes.encrypt(nonce, piece, b"last" if last else b"more")
        dst.write(struct.pack(">I", len(ct)) + nonce + ct)
        if last:
            return
        piece, n = nxt, n + 1


def decrypt_stream(src, dst, key=None):
    aes = AESGCM(key or _key())
    if src.read(len(MAGIC)) != MAGIC:
        raise BackupError("Not a ZENTAVA backup file")
    n = 0
    while True:
        head = src.read(4)
        if not head:
            raise BackupError("The backup file is incomplete (it was cut off)")
        size = struct.unpack(">I", head)[0]
        nonce, ct = src.read(12), src.read(size)
        if len(nonce) != 12 or len(ct) != size or nonce[4:] != struct.pack(">Q", n):
            raise BackupError("The backup file is damaged")
        for aad in (b"more", b"last"):
            try:
                dst.write(aes.decrypt(nonce, ct, aad))
                break
            except Exception:  # noqa: BLE001 - wrong marker or wrong key: try the other marker, then fail
                if aad == b"last":
                    raise BackupError("The backup cannot be decrypted: wrong BACKUP_ENCRYPTION_KEY or a damaged file")
        if aad == b"last":
            if src.read(1):
                raise BackupError("The backup file has unexpected data at the end")
            return
        n += 1


# --- where backups are kept ------------------------------------------------------------------

class DirTarget:
    def __init__(self, root):
        self.root = os.path.abspath(root)

    def _p(self, name):
        p = os.path.abspath(os.path.join(self.root, name))
        if not p.startswith(self.root + os.sep):
            raise BackupError("Invalid backup name")
        return p

    def put_file(self, name, path):
        dest = self._p(name)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(path, dest + ".part")
        os.replace(dest + ".part", dest)

    def get_file(self, name, path):
        if not os.path.exists(self._p(name)):
            raise BackupError(f"Backup {name} not found")
        shutil.copyfile(self._p(name), path)

    def exists(self, name):
        return os.path.exists(self._p(name))

    def list(self, prefix):
        base = self._p(prefix.rstrip("/") or ".") if prefix else self.root
        out = []
        for dirpath, _, files in os.walk(base):
            for f in files:
                if not f.endswith(".part"):
                    out.append(os.path.relpath(os.path.join(dirpath, f), self.root).replace(os.sep, "/"))
        return sorted(out)

    def delete(self, name):
        try:
            os.remove(self._p(name))
        except FileNotFoundError:
            pass


class S3Target:
    def __init__(self, cfg):
        import boto3
        self.bucket = cfg["BACKUP_S3_BUCKET"]
        self.prefix = (cfg.get("BACKUP_S3_PREFIX") or "").strip("/")
        self.prefix = self.prefix + "/" if self.prefix else ""
        self.client = boto3.client("s3", endpoint_url=cfg.get("BACKUP_S3_ENDPOINT_URL") or None,
                                   region_name=cfg.get("BACKUP_S3_REGION") or None,
                                   aws_access_key_id=cfg.get("BACKUP_S3_ACCESS_KEY_ID") or None,
                                   aws_secret_access_key=cfg.get("BACKUP_S3_SECRET_ACCESS_KEY") or None)

    def put_file(self, name, path):
        self.client.upload_file(path, self.bucket, self.prefix + name)

    def get_file(self, name, path):
        try:
            self.client.download_file(self.bucket, self.prefix + name, path)
        except Exception as exc:  # noqa: BLE001 - boto raises several kinds; report plainly
            raise BackupError(f"Backup {name} could not be downloaded: {exc}") from exc

    def exists(self, name):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self.prefix + name)
            return True
        except Exception:  # noqa: BLE001 - not found (or no access): treat as missing
            return False

    def list(self, prefix):
        out, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": self.prefix + prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = self.client.list_objects_v2(**kw)
            out += [o["Key"][len(self.prefix):] for o in resp.get("Contents", [])]
            if not resp.get("IsTruncated"):
                return sorted(out)
            token = resp["NextContinuationToken"]

    def delete(self, name):
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + name)


def get_target():
    cfg = current_app.config
    if cfg.get("BACKUP_S3_BUCKET"):
        if cfg.get("BACKUP_S3_BUCKET") == cfg.get("S3_BUCKET") and not cfg.get("BACKUP_S3_PREFIX"):
            raise BackupError("Use a separate bucket (or at least BACKUP_S3_PREFIX) for backups")
        return S3Target(cfg)
    if cfg.get("BACKUP_DIR"):
        return DirTarget(cfg["BACKUP_DIR"])
    raise BackupError("No backup destination: set BACKUP_S3_BUCKET (recommended) or BACKUP_DIR")


# --- database tables -------------------------------------------------------------------------

def _require_postgres():
    if db.engine.dialect.name != "postgresql":
        raise BackupError("Backups need PostgreSQL")


def _tables():
    """Application tables in a safe load order, with their columns and the links to fill in afterwards.

    A table is loaded once every table it links to is loaded. Where tables link to each other in a circle,
    a link that may be empty is left empty at first and filled in at the end (as are links within a table)."""
    insp = inspect(db.engine)
    names = sorted(t for t in insp.get_table_names() if t != "alembic_version")
    info = {}
    for t in names:
        cols = insp.get_columns(t)
        nullable = {c["name"]: c["nullable"] for c in cols}
        edges = []   # (referred table, columns, all columns may be empty)
        for fk in insp.get_foreign_keys(t):
            cs = fk["constrained_columns"]
            edges.append((fk["referred_table"], cs, all(nullable[c] for c in cs)))
        info[t] = {"columns": [c["name"] for c in cols], "edges": edges,
                   "pk": insp.get_pk_constraint(t).get("constrained_columns") or [cols[0]["name"]]}
    order, done, deferred = [], set(), {t: set() for t in names}
    pending = list(names)
    while pending:
        ready = [t for t in pending if all(ref == t or ref in done for ref, _, _ in info[t]["edges"])]
        if not ready:
            # A circle: take the table whose missing links can all be left empty for now (fewest first)
            options = []
            for t in pending:
                missing = [(ref, cs, ok) for ref, cs, ok in info[t]["edges"] if ref != t and ref not in done]
                if all(ok for _, _, ok in missing):
                    options.append((len(missing), t, missing))
            if not options:
                raise BackupError(f"Cannot find a load order for tables {pending}")
            _, t, missing = min(options)
            for _, cs, _ in missing:
                deferred[t].update(cs)
            ready = [t]
        for t in ready:
            order.append(t)
            done.add(t)
            pending.remove(t)
    out = []
    for t in order:
        self_links = [c for ref, cs, ok in info[t]["edges"] if ref == t for c in cs]
        for ref, cs, ok in info[t]["edges"]:
            if ref == t and not ok:
                raise BackupError(f"Table {t} has a required link to itself")
        out.append({"name": t, "columns": info[t]["columns"], "pk": info[t]["pk"],
                    "deferred": sorted(deferred[t] | set(self_links))})
    return out


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _revision():
    return db.session.execute(text("select version_num from alembic_version")).scalar()


# --- backup ----------------------------------------------------------------------------------

def _file_keys():
    from app.models import DocumentVersion
    from app.tenancy import unscoped
    from sqlalchemy import select
    return sorted(db.session.execute(unscoped(select(DocumentVersion.storage_key))).scalars())


def backup_files(target, log=print):
    """Copy uploaded files that the backup does not have yet (stored files never change)."""
    from app.storage import StorageError, get_storage
    store = get_storage()
    have = set(target.list("files/"))
    added = missing = 0
    with tempfile.TemporaryDirectory() as tmp:
        for key in _file_keys():
            name = f"files/{key}.enc"
            if name in have:
                continue
            try:
                data = store.get(key)
            except StorageError:
                missing += 1
                log(f"  file missing from storage, not backed up: {key}")
                continue
            path = os.path.join(tmp, "f.enc")
            with open(path, "wb") as out:
                encrypt_stream(io.BytesIO(data), out)
            target.put_file(name, path)
            added += 1
    return added, missing


def create_backup(target=None, include_files=True, log=print):
    """Back up the database (and new uploaded files). Returns the backup's name."""
    _require_postgres()
    target = target or get_target()
    key = _key()   # fail early if missing
    now = datetime.now(timezone.utc)
    name = f"zentava-{now:%Y%m%d-%H%M%S}.ztvbak"
    manifest = {"format": 1, "created_at": now.isoformat(), "app_version": current_app.config.get("OIMS_VERSION"),
                "revision": None, "tables": {}}
    with tempfile.TemporaryDirectory() as tmp:
        tar_path = os.path.join(tmp, "backup.tar")
        conn = db.engine.raw_connection()
        try:
            dbapi = conn.driver_connection
            dbapi.rollback()
            dbapi.autocommit = True   # transactions below are explicit
            # One consistent snapshot of every table, even while people keep working
            with dbapi.cursor() as cur:
                cur.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("select version_num from alembic_version")
                manifest["revision"] = cur.fetchone()[0]
            with tarfile.open(tar_path, "w") as tar:
                for t in _tables():
                    part = os.path.join(tmp, "t.csv.gz")
                    digest = hashlib.sha256()
                    with dbapi.cursor() as cur:   # exact count (a text field may span several lines)
                        rows = cur.execute(f"select count(*) from {_q(t['name'])}").fetchone()[0]
                    order = ", ".join(_q(c) for c in t["pk"])
                    cols = ", ".join(_q(c) for c in t["columns"])
                    sql = f"COPY (SELECT {cols} FROM {_q(t['name'])} ORDER BY {order}) TO STDOUT WITH (FORMAT csv, HEADER)"
                    with dbapi.cursor() as cur, gzip.open(part, "wb") as gz:
                        with cur.copy(sql) as copy:
                            for chunk in copy:
                                chunk = bytes(chunk)
                                digest.update(chunk)
                                gz.write(chunk)
                    manifest["tables"][t["name"]] = {"columns": t["columns"], "sha256": digest.hexdigest(),
                                                     "rows": rows}
                    tar.add(part, arcname=f"db/{t['name']}.csv.gz")
                    log(f"  {t['name']}: {rows} rows")
                data = json.dumps(manifest, indent=1).encode()
                info = tarfile.TarInfo("manifest.json")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            with dbapi.cursor() as cur:
                cur.execute("COMMIT")
        finally:
            if dbapi.info.transaction_status != 0:   # not idle: end the snapshot
                dbapi.execute("ROLLBACK")
            dbapi.autocommit = False
            conn.close()
        enc = os.path.join(tmp, name)
        with open(tar_path, "rb") as src, open(enc, "wb") as dst:
            encrypt_stream(src, dst, key)
        target.put_file(f"db/{name}", enc)
        log(f"Database backup {name}: {os.path.getsize(enc) // 1024} KB")
    if include_files:
        added, missing = backup_files(target, log)
        log(f"Files: {added} new file(s) backed up" + (f", {missing} missing from storage" if missing else ""))
    prune(target, log)
    return name


def prune(target, log=print, today=None):
    """Keep the last BACKUP_KEEP_DAILY days and the first backup of each of the last BACKUP_KEEP_MONTHLY months."""
    cfg = current_app.config
    days, months = cfg.get("BACKUP_KEEP_DAILY", 14), cfg.get("BACKUP_KEEP_MONTHLY", 12)
    today = today or datetime.now(timezone.utc).date()
    names = [n.split("/", 1)[1] for n in target.list("db/") if NAME_RE.match(n.split("/", 1)[-1])]
    keep, first_of_month = set(), {}
    for n in sorted(names):
        d = datetime.strptime(NAME_RE.match(n).group(1), "%Y%m%d").date()
        if (today - d).days < days:
            keep.add(n)
        first_of_month.setdefault((d.year, d.month), n)
    for (y, m), n in first_of_month.items():
        if (today.year - y) * 12 + (today.month - m) < months:
            keep.add(n)
    if names:
        keep.add(sorted(names)[-1])   # never delete the newest backup
    for n in names:
        if n not in keep:
            target.delete(f"db/{n}")
            log(f"  removed old backup {n}")


def list_backups(target=None):
    target = target or get_target()
    return [n.split("/", 1)[1] for n in target.list("db/") if NAME_RE.match(n.split("/", 1)[-1])]


# --- restore ---------------------------------------------------------------------------------

def _open_backup(target, name, tmp):
    enc = os.path.join(tmp, "in.ztvbak")
    if os.path.exists(name):          # a local file given by path
        shutil.copyfile(name, enc)
    else:
        target.get_file(f"db/{name}", enc)
    tar_path = os.path.join(tmp, "in.tar")
    with open(enc, "rb") as src, open(tar_path, "wb") as dst:
        decrypt_stream(src, dst)
    tar = tarfile.open(tar_path, "r")
    manifest = json.loads(tar.extractfile("manifest.json").read())
    return tar, manifest


def verify_backup(name, target=None, log=print):
    """Decrypt a backup and check every table against its checksum. Returns the manifest."""
    target = target or (None if os.path.exists(name) else get_target())
    with tempfile.TemporaryDirectory() as tmp:
        tar, manifest = _open_backup(target, name, tmp)
        with tar:
            for t, meta in manifest["tables"].items():
                digest = hashlib.sha256()
                with gzip.open(tar.extractfile(f"db/{t}.csv.gz")) as gz:
                    for chunk in iter(lambda: gz.read(CHUNK), b""):
                        digest.update(chunk)
                if digest.hexdigest() != meta["sha256"]:
                    raise BackupError(f"Table {t} does not match its checksum")
        log(f"{name}: {len(manifest['tables'])} tables, all checksums match "
            f"(schema {manifest['revision']}, made {manifest['created_at']})")
        return manifest


def _database_is_empty():
    insp = inspect(db.engine)
    names = set(insp.get_table_names())
    for t in ("organizations", "users"):
        if t in names and db.session.execute(text(f"select exists (select 1 from {t})")).scalar():
            return False
    return True


def restore_backup(name, target=None, with_files=True, log=print):
    """Load a backup into an empty database (and put its files back into document storage)."""
    from flask_migrate import upgrade
    _require_postgres()
    if not _database_is_empty():
        raise BackupError("This database already has data. Restore only into a new, empty database.")
    target = target or (None if os.path.exists(name) else get_target())
    with tempfile.TemporaryDirectory() as tmp:
        tar, manifest = _open_backup(target, name, tmp)
        with tar:
            log(f"Bringing the empty database to the backup's schema ({manifest['revision']})")
            db.session.remove()
            upgrade(revision=manifest["revision"])
            tables = {t["name"]: t for t in _tables()}
            missing = set(manifest["tables"]) - set(tables)
            if missing:
                raise BackupError(f"Tables in the backup are unknown to this schema: {sorted(missing)}")
            conn = db.engine.raw_connection()
            dbapi = conn.driver_connection
            dbapi.rollback()
            dbapi.autocommit = True   # one explicit transaction: all of the restore, or nothing
            try:
                with dbapi.cursor() as cur:
                    cur.execute("BEGIN")
                    later = []
                    for t in [x for x in _tables() if x["name"] in manifest["tables"]]:
                        meta = manifest["tables"][t["name"]]
                        cols = ", ".join(_q(c) for c in meta["columns"])
                        digest = hashlib.sha256()
                        dest = _q(t["name"])
                        deferred = [c for c in t["deferred"] if c in meta["columns"]]
                        if deferred:   # load into a scratch copy first, then copy across without forward links
                            scratch = _q("restore_" + t["name"])
                            # scratch copy: no defaults (every column comes from the backup); gone at the end
                            cur.execute(f"CREATE TEMP TABLE {scratch} (LIKE {dest}) ON COMMIT DROP")
                            dest = scratch
                        with gzip.open(tar.extractfile(f"db/{t['name']}.csv.gz")) as gz:
                            with cur.copy(f"COPY {dest} ({cols}) FROM STDIN WITH (FORMAT csv, HEADER)") as copy:
                                for chunk in iter(lambda: gz.read(CHUNK), b""):
                                    digest.update(chunk)
                                    copy.write(chunk)
                        if digest.hexdigest() != meta["sha256"]:
                            raise BackupError(f"Table {t['name']} does not match its checksum")
                        if deferred:
                            sel = ", ".join("NULL" if c in deferred else _q(c) for c in meta["columns"])
                            cur.execute(f"INSERT INTO {_q(t['name'])} ({cols}) SELECT {sel} FROM {dest}")
                            later.append((t, deferred, dest))
                    for t, deferred, scratch in later:   # now every linked row exists: fill the links in
                        sets = ", ".join(f"{_q(c)} = s.{_q(c)}" for c in deferred)
                        keys = " AND ".join(f"d.{_q(k)} = s.{_q(k)}" for k in t["pk"])
                        cur.execute(f"UPDATE {_q(t['name'])} d SET {sets} FROM {scratch} s WHERE {keys}")
                    for t in manifest["tables"]:   # counts must match exactly
                        n = cur.execute(f"select count(*) from {_q(t)}").fetchone()[0]
                        expected = manifest["tables"][t]["rows"]
                        if n != expected:
                            raise BackupError(f"Table {t}: {n} rows restored, {expected} expected")
                    # id counters continue after the restored rows
                    cur.execute("""select table_name, column_name, pg_get_serial_sequence(quote_ident(table_name),
                                   column_name) from information_schema.columns where table_schema = 'public'
                                   and column_default like 'nextval%'""")
                    for table, col, seq in cur.fetchall():
                        if seq:
                            cur.execute(f"select setval('{seq}', coalesce((select max({_q(col)}) from "
                                        f"{_q(table)}), 0) + 1, false)")
                    cur.execute("COMMIT")
            except Exception:
                try:
                    if dbapi.info.transaction_status != 0:
                        dbapi.execute("ROLLBACK")
                finally:
                    dbapi.autocommit = False
                    conn.close()
                raise
            dbapi.autocommit = False
            conn.close()
            restored = sum(m["rows"] for m in manifest["tables"].values())
            log(f"Restored {len(manifest['tables'])} tables ({restored} rows)")
    db.session.remove()
    log("Upgrading to the current schema")
    upgrade()
    if with_files:
        put, missing = restore_files(target, log)
        log(f"Files: {put} restored" + (f", {missing} not found in the backup" if missing else ""))


def restore_files(target, log=print):
    from app.storage import get_storage
    store = get_storage()
    have = set(target.list("files/")) if target else set()
    put = missing = 0
    for key in _file_keys():
        name = f"files/{key}.enc"
        if name not in have:
            missing += 1
            continue
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "f.enc")
            target.get_file(name, path)
            out = io.BytesIO()
            with open(path, "rb") as src:
                decrypt_stream(src, out)
            store.put(key, out.getvalue(), "application/octet-stream")
            put += 1
    return put, missing
