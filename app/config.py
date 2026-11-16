"""Environment-based configuration. All secrets come from environment variables."""
import os
from datetime import timedelta


def _bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _database_url():
    url = os.environ.get("DATABASE_URL", "")
    # Render / Heroku style URLs use the legacy "postgres://" scheme.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # Use the psycopg 3 driver explicitly.
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class BaseConfig:
    APP_NAME = "ZENTAVA OIMS"
    BRAND_NAME = "ZENTAVA"          # the brand (wordmark, logo)
    PRODUCT_NAME = "OIMS"           # the product shown beside the brand
    APP_FULL_NAME = "Organized. Transparent. Accountable."
    PLATFORM_OWNER = "Kayron Global Tech Services"

    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Sessions & cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", True)
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    PERMANENT_SESSION_LIFETIME = timedelta(hours=int(os.environ.get("SESSION_HOURS", "8")))

    WTF_CSRF_TIME_LIMIT = 60 * 60 * 4

    # Rate limiting (use Redis in multi-instance production)
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_HEADERS_ENABLED = True

    # Account protection
    LOGIN_MAX_FAILURES = int(os.environ.get("LOGIN_MAX_FAILURES", "5"))
    LOGIN_LOCKOUT_MINUTES = int(os.environ.get("LOGIN_LOCKOUT_MINUTES", "15"))
    PASSWORD_MIN_LENGTH = int(os.environ.get("PASSWORD_MIN_LENGTH", "12"))
    PASSWORD_RESET_MAX_AGE = int(os.environ.get("PASSWORD_RESET_MAX_AGE", str(60 * 60 * 24)))

    # First-run setup: the /setup page only works when this token is set
    SETUP_TOKEN = os.environ.get("OIMS_SETUP_TOKEN")

    # Support access
    SUPPORT_ACCESS_MAX_MINUTES = int(os.environ.get("SUPPORT_ACCESS_MAX_MINUTES", "120"))

    # Online payments through Paystack (card and mobile money). Leave empty to accept bank transfers only.
    PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY") or None
    PAYSTACK_API_BASE = os.environ.get("PAYSTACK_API_BASE", "https://api.paystack.co")

    # Outgoing email (real SMTP; if not configured, links are written to the server log)
    SMTP_HOST = os.environ.get("SMTP_HOST")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    SMTP_USE_TLS = _bool("SMTP_USE_TLS", True)
    MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@zentava.local")
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL")  # e.g. https://zentava.example.org

    # Document storage: "local" (a directory / persistent disk) or "s3" (S3-compatible object storage)
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()
    UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT", "")
    S3_BUCKET = os.environ.get("S3_BUCKET")
    S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL")      # blank for AWS; set for R2, B2, Spaces, MinIO
    S3_REGION = os.environ.get("S3_REGION")
    S3_ACCESS_KEY_ID = os.environ.get("S3_ACCESS_KEY_ID")
    S3_SECRET_ACCESS_KEY = os.environ.get("S3_SECRET_ACCESS_KEY")
    S3_PREFIX = os.environ.get("S3_PREFIX", "")
    S3_SERVER_SIDE_ENCRYPTION = _bool("S3_SERVER_SIDE_ENCRYPTION", True)
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024

    # Two-step sign-in is required for Kayron platform staff unless switched off.
    REQUIRE_PLATFORM_2FA = _bool("REQUIRE_PLATFORM_2FA", True)

    ALLOW_PUBLIC_REGISTRATION = _bool("ALLOW_PUBLIC_REGISTRATION", True)

    # Large downloads prepared at the same time per server process, and how long to wait for a turn (seconds)
    HEAVY_DOWNLOADS = int(os.environ.get("HEAVY_DOWNLOADS", "1"))
    HEAVY_DOWNLOAD_WAIT = int(os.environ.get("HEAVY_DOWNLOAD_WAIT", "20"))


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-only-not-secret"
    SQLALCHEMY_DATABASE_URI = _database_url() or "sqlite:///oims-dev.sqlite3"
    UPLOAD_ROOT = os.environ.get("UPLOAD_ROOT") or os.path.join(os.getcwd(), "uploads")
    REQUIRE_PLATFORM_2FA = _bool("REQUIRE_PLATFORM_2FA", False)


class TestingConfig(BaseConfig):
    TESTING = True
    SECRET_KEY = "test-secret"
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    RATELIMIT_ENABLED = False
    PASSWORD_MIN_LENGTH = 12
    SETUP_TOKEN = "test-setup-token"
    STORAGE_BACKEND = "local"
    REQUIRE_PLATFORM_2FA = False


class ProductionConfig(BaseConfig):
    pass


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
