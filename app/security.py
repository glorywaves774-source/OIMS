"""Password policy, signed tokens, safe redirects, security headers and email."""
import logging
import re
import smtplib
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import abort, current_app, request, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

log = logging.getLogger("oims")

COMMON_PASSWORDS = {
    "password1234", "123456789012", "qwertyuiop12", "letmein12345", "administrator",
    "password123!", "welcome12345", "changeme1234", "holido123456", "kayron123456", "oims12345678",
}


def password_problems(password, email=None, name=None):
    """Return a list of human-readable reasons the password is too weak (empty if OK)."""
    problems = []
    min_len = current_app.config["PASSWORD_MIN_LENGTH"]
    if len(password) < min_len:
        problems.append(f"Use at least {min_len} characters.")
    classes = sum(bool(re.search(p, password)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    if classes < 3:
        problems.append("Mix at least three of: lowercase, uppercase, numbers, symbols.")
    low = password.lower()
    if low in COMMON_PASSWORDS:
        problems.append("This password is too common.")
    if email and email.split("@")[0].lower() in low and len(email.split("@")[0]) >= 4:
        problems.append("Do not include your email name in the password.")
    return problems


# --- Signed tokens ----------------------------------------------------------

def _serializer(salt):
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=salt)


def make_password_token(user):
    # Binding to the current hash makes the token single-use: it dies when the password changes.
    fingerprint = (user.password_hash or "unset")[-16:]
    return _serializer("password-reset").dumps({"uid": user.id, "fp": fingerprint})


def read_password_token(token, max_age=None):
    from app.models import User
    from app.extensions import db

    max_age = max_age or current_app.config["PASSWORD_RESET_MAX_AGE"]
    try:
        data = _serializer("password-reset").loads(token, max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(User, data.get("uid"))
    if user is None or not user.is_enabled:
        return None
    if (user.password_hash or "unset")[-16:] != data.get("fp"):
        return None
    return user


def external_url(endpoint, **values):
    base = current_app.config.get("PUBLIC_BASE_URL")
    path = url_for(endpoint, **values)
    if base:
        return urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    return url_for(endpoint, _external=True, **values)


# --- Redirect safety --------------------------------------------------------

def is_safe_next(target):
    if not target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme and target.startswith("/") and not target.startswith("//")


# --- Access decorators -------------------------------------------------------

def platform_required(*roles):
    """Restrict a view to Kayron platform staff (optionally specific platform roles)."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return current_app.login_manager.unauthorized()
            if not current_user.is_platform_staff:
                abort(403)
            if roles and current_user.platform_role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


# --- Email -------------------------------------------------------------------

def mail_configured():
    return bool(current_app.config.get("SMTP_HOST"))


def send_email(to, subject, body):
    """Send a plain-text email over SMTP. Returns True if sent.

    When SMTP is not configured the message is written to the server log so an
    operator can relay it; callers show the link on screen to authorized admins.
    """
    cfg = current_app.config
    if not mail_configured():
        log.warning("SMTP not configured; email to %s not sent. Subject: %s", to, subject)
        return False
    msg = EmailMessage()
    msg["From"] = cfg["MAIL_FROM"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15) as smtp:
            if cfg["SMTP_USE_TLS"]:
                smtp.starttls()
            if cfg.get("SMTP_USERNAME"):
                smtp.login(cfg["SMTP_USERNAME"], cfg["SMTP_PASSWORD"] or "")
            smtp.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Email to %s failed: %s", to, exc)
        return False


# --- Headers -----------------------------------------------------------------

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
    "form-action 'self'; object-src 'none'"
)


def apply_security_headers(response):
    response.headers.setdefault("Content-Security-Policy", CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.endpoint and not request.endpoint.startswith("static"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response
