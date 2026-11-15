"""File storage for uploaded documents.

Two backends:
- ``local``: a directory on disk (development, or a persistent disk mounted on the server);
- ``s3``: any S3-compatible object store (AWS S3, Cloudflare R2, Backblaze B2, DigitalOcean
  Spaces, MinIO) through boto3.

Files are stored under random keys prefixed with the organization id — never under the
uploaded file name — and are always served through the application, which checks
permissions first.
"""
import hashlib
import io
import os
import uuid
import zipfile

from flask import current_app


class StorageError(RuntimeError):
    pass


class UploadRejected(ValueError):
    pass


# extension -> (mime type, signature check)
def _is_ooxml(data, folder):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and any(n.startswith(folder + "/") for n in names)


def _is_odf(data):
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "mimetype" in z.namelist()
    except zipfile.BadZipFile:
        return False


def _is_text(data):
    if b"\x00" in data[:8192]:
        return False
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        try:
            data[:65536].decode("latin-1")
        except UnicodeDecodeError:  # pragma: no cover
            return False
    return True


OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
ALLOWED = {
    "pdf": ("application/pdf", lambda d: d.startswith(b"%PDF-")),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", lambda d: _is_ooxml(d, "word")),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", lambda d: _is_ooxml(d, "xl")),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", lambda d: _is_ooxml(d, "ppt")),
    "doc": ("application/msword", lambda d: d.startswith(OLE)),
    "xls": ("application/vnd.ms-excel", lambda d: d.startswith(OLE)),
    "ppt": ("application/vnd.ms-powerpoint", lambda d: d.startswith(OLE)),
    "odt": ("application/vnd.oasis.opendocument.text", _is_odf),
    "ods": ("application/vnd.oasis.opendocument.spreadsheet", _is_odf),
    "odp": ("application/vnd.oasis.opendocument.presentation", _is_odf),
    "csv": ("text/csv", _is_text),
    "txt": ("text/plain", _is_text),
    "png": ("image/png", lambda d: d.startswith(b"\x89PNG\r\n\x1a\n")),
    "jpg": ("image/jpeg", lambda d: d.startswith(b"\xff\xd8\xff")),
    "jpeg": ("image/jpeg", lambda d: d.startswith(b"\xff\xd8\xff")),
    "webp": ("image/webp", lambda d: d[:4] == b"RIFF" and d[8:12] == b"WEBP"),
    "gif": ("image/gif", lambda d: d[:6] in (b"GIF87a", b"GIF89a")),
}
ALLOWED_EXTENSIONS_TEXT = "PDF, Word, Excel, PowerPoint, OpenDocument, CSV, text and images (PNG, JPEG, WebP, GIF)"


def safe_filename(name):
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    keep = "".join(c for c in name if c.isalnum() or c in " ._-()[]").strip(" .")
    return (keep or "file")[:200]


def inspect_upload(file_storage):
    """Read and validate an upload. Returns dict(data, filename, mime, size, sha256)."""
    if not file_storage or not getattr(file_storage, "filename", ""):
        raise UploadRejected("Choose a file to upload.")
    filename = safe_filename(file_storage.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED:
        raise UploadRejected(f"This file type is not allowed. Allowed: {ALLOWED_EXTENSIONS_TEXT}.")
    max_bytes = current_app.config["MAX_CONTENT_LENGTH"]
    data = file_storage.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadRejected(f"The file is larger than {max_bytes // (1024 * 1024)} MB.")
    if not data:
        raise UploadRejected("The file is empty.")
    mime, check = ALLOWED[ext]
    if not check(data):
        raise UploadRejected(f"The file's content does not match its .{ext} extension.")
    return {"data": data, "filename": filename, "mime": mime, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def new_key(organization_id):
    return f"org-{organization_id}/{uuid.uuid4().hex}"


class LocalStorage:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _path(self, key):
        path = os.path.abspath(os.path.join(self.root, key))
        if not path.startswith(self.root + os.sep):
            raise StorageError("Invalid storage key")
        return path

    def put(self, key, data, mime):
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)

    def get(self, key):
        try:
            with open(self._path(key), "rb") as fh:
                return fh.read()
        except FileNotFoundError as exc:
            raise StorageError("File is missing from storage") from exc

    def delete(self, key):
        try:
            os.remove(self._path(key))
        except FileNotFoundError:
            pass

    def check(self):
        return os.access(self.root, os.W_OK)


class S3Storage:
    def __init__(self, bucket, endpoint_url=None, region=None, access_key=None, secret_key=None, prefix=""):
        import boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix else ""
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region or None,
                                   aws_access_key_id=access_key or None, aws_secret_access_key=secret_key or None)

    def put(self, key, data, mime):
        extra = {"ServerSideEncryption": "AES256"} if current_app.config.get("S3_SERVER_SIDE_ENCRYPTION", True) else {}
        self.client.put_object(Bucket=self.bucket, Key=self.prefix + key, Body=data, ContentType=mime, **extra)

    def get(self, key):
        try:
            return self.client.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()
        except self.client.exceptions.NoSuchKey as exc:
            raise StorageError("File is missing from storage") from exc

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self.prefix + key)

    def check(self):
        self.client.head_bucket(Bucket=self.bucket)
        return True


def get_storage():
    app = current_app._get_current_object()
    store = app.extensions.get("oims_storage")
    if store is None:
        cfg = app.config
        if cfg["STORAGE_BACKEND"] == "s3":
            store = S3Storage(cfg["S3_BUCKET"], cfg.get("S3_ENDPOINT_URL"), cfg.get("S3_REGION"),
                              cfg.get("S3_ACCESS_KEY_ID"), cfg.get("S3_SECRET_ACCESS_KEY"), cfg.get("S3_PREFIX", ""))
        else:
            store = LocalStorage(cfg["UPLOAD_ROOT"])
        app.extensions["oims_storage"] = store
    return store
