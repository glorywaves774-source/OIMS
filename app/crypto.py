"""Field-level protection for personal data (beneficiary phone numbers, ID numbers, contacts).

Values are encrypted with a key derived from SECRET_KEY, so a copy of the database alone does not
reveal them. A keyed hash ("blind index") of the normalized value lets the app find duplicates
without decrypting every row. Changing SECRET_KEY makes existing values unreadable — keep it stable
(see docs/DEPLOYMENT.md).
"""
import base64
import hashlib
import hmac
import re
import unicodedata

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


def _key(purpose):
    return hashlib.sha256((f"oims-{purpose}:" + current_app.config["SECRET_KEY"]).encode()).digest()


def encrypt_text(value):
    if not value:
        return None
    return Fernet(base64.urlsafe_b64encode(_key("pii"))).encrypt(value.encode()).decode()


def decrypt_text(token):
    if not token:
        return None
    try:
        return Fernet(base64.urlsafe_b64encode(_key("pii"))).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def normalize(value, kind="text"):
    """Lower-case, accents removed, spaces collapsed; phone numbers reduced to their last 9 digits."""
    if not value:
        return ""
    if kind == "phone":
        digits = re.sub(r"\D", "", value)
        return digits[-9:]
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def blind_index(value, kind="text"):
    norm = normalize(value, kind)
    if not norm:
        return None
    return hmac.new(_key("pii-index"), f"{kind}:{norm}".encode(), hashlib.sha256).hexdigest()
