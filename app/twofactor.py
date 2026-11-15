"""Two-step sign-in with authenticator apps (TOTP, RFC 6238) and recovery codes."""
import base64
import datetime
import hashlib
import io
import secrets

import pyotp
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

ISSUER = "ZENTAVA"


def _fernet():
    key = hashlib.sha256(("oims-totp:" + current_app.config["SECRET_KEY"]).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_secret(secret):
    return _fernet().encrypt(secret.encode()).decode()


def decrypt_secret(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, AttributeError):
        return None


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(secret, email):
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=ISSUER)


def qr_data_uri(uri):
    import qrcode
    import qrcode.image.svg

    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def check_code(secret, code, last_counter=None):
    """Return the matched time-step counter, or None. Rejects reuse of a code already used."""
    code = (code or "").replace(" ", "").strip()
    if not code.isdigit() or len(code) != 6 or not secret:
        return None
    totp = pyotp.TOTP(secret)
    now_counter = totp.timecode(datetime.datetime.now())
    for offset in (-1, 0, 1):
        counter = now_counter + offset
        if secrets.compare_digest(totp.generate_otp(counter), code):
            if last_counter is not None and counter <= last_counter:
                return None
            return counter
    return None


def verify_user_code(user, code):
    """Check a 6-digit code (or a recovery code) for ``user``; updates the user on success."""
    secret = decrypt_secret(user.totp_secret_enc) if user.totp_secret_enc else None
    counter = check_code(secret, code, user.totp_last_counter)
    if counter is not None:
        user.totp_last_counter = counter
        return "totp"
    if use_recovery_code(user, code):
        return "recovery"
    return None


def new_recovery_codes(n=10):
    codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(n)]
    return codes, [generate_password_hash(c, method="scrypt") for c in codes]


def use_recovery_code(user, code):
    code = (code or "").strip().lower()
    if len(code) != 14 or not user.recovery_codes:
        return False
    remaining = list(user.recovery_codes)
    for h in remaining:
        if check_password_hash(h, code):
            remaining.remove(h)
            user.recovery_codes = remaining
            return True
    return False
