"""ZENTAVA OIMS (Kayron). Application factory. Internal package and CLI names stay "oims"."""
import logging
import os

from flask import Flask, g, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import CONFIGS
from app.extensions import csrf, db, limiter, login_manager, migrate

__version__ = "0.9.6-plans"


def create_app(config_name=None, overrides=None):
    config_name = config_name or os.environ.get("OIMS_ENV", "production")
    app = Flask(__name__)
    app.config.from_object(CONFIGS[config_name])
    if overrides:
        app.config.update(overrides)
    app.config["OIMS_VERSION"] = __version__
    app.config["OIMS_CONFIG_NAME"] = config_name

    _check_production_config(app, config_name)
    _tune_database(app)
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Render and most PaaS hosts terminate TLS at a proxy.
    if os.environ.get("TRUST_PROXY", "1") == "1":
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    login_manager.session_protection = "strong"

    from app import tenancy  # noqa: F401  (registers the isolation guard)
    from app.models import User

    @login_manager.user_loader
    def load_user(token):
        try:
            uid, version = token.split(".", 1)
            user = db.session.get(User, int(uid))
        except (ValueError, TypeError):
            return None
        if user is None or str(user.session_version) != version or not user.is_enabled:
            return None
        return user

    from app.blueprints.account import bp as account_bp
    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.platform import bp as platform_bp
    from app.blueprints.public import bp as public_bp
    from app.blueprints.setup import bp as setup_bp
    from app.blueprints.workspace import bp as workspace_bp
    from app.blueprints.people import attendance_bp, departments_bp, leave_bp, staff_bp
    from app.blueprints.documents import bp as documents_bp
    from app.blueprints.correspondence import bp as correspondence_bp
    from app.blueprints.meetings import bp as meetings_bp
    from app.blueprints.tasks import bp as tasks_bp
    from app.blueprints.comms import bp as comms_bp
    from app.blueprints.programmes import programmes_bp, projects_bp
    from app.blueprints import programme_finance  # noqa: F401  (adds finance routes to programmes_bp)
    from app.blueprints import project_extras  # noqa: F401  (work breakdown, deliverables, risks, closure)
    from app.blueprints.programme_reports import registers as registers_bp  # also adds report routes
    from app.blueprints import owner_meal  # noqa: F401  (beneficiaries tab and named attendance)
    from app.blueprints.beneficiaries import bp as beneficiaries_bp
    from app.blueprints.meal import bp as meal_bp
    from app.blueprints.feedback import bp as feedback_bp, public_bp as public_feedback_bp
    from app.blueprints.procurement import bp as procurement_bp
    from app.blueprints.assets import bp as assets_bp
    from app.blueprints.finance import bp as finance_bp
    from app.blueprints.analytics import bp as analytics_bp
    from app.blueprints.billing import bp as billing_bp, hooks as billing_hooks_bp
    from app.blueprints.platform_billing import bp as platform_billing_bp
    from app.blueprints.assistant import bp as assistant_bp, global_bp as assistant_global_bp
    from app.blueprints.pwa import bp as pwa_bp

    for bp in (public_bp, auth_bp, setup_bp, account_bp, platform_bp, workspace_bp, departments_bp, staff_bp,
               leave_bp, attendance_bp, documents_bp, correspondence_bp, meetings_bp, tasks_bp, comms_bp,
               programmes_bp, projects_bp, registers_bp, beneficiaries_bp, meal_bp, feedback_bp, public_feedback_bp,
               procurement_bp, assets_bp, finance_bp, analytics_bp,
               billing_bp, billing_hooks_bp, platform_billing_bp, assistant_bp, assistant_global_bp, pwa_bp):
        app.register_blueprint(bp)

    _register_template_globals(app)
    _register_hooks(app)
    from app import i18n
    i18n.init_app(app)
    _register_errors(app)

    from app.cli import register_cli
    register_cli(app)
    return app


def _tune_database(app):
    """PostgreSQL: plan every query for its actual values.

    After a few repeats PostgreSQL may switch a prepared query to a generic plan; for lists of ids that plan
    can be many times slower (measured: 0.2 s instead of 0.007 s). Planning each time costs well under a
    millisecond."""
    uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if uri.startswith("postgresql"):
        opts = dict(app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {})
        args = dict(opts.get("connect_args") or {})
        args["options"] = (args.get("options", "") + " -c plan_cache_mode=force_custom_plan").strip()
        opts["connect_args"] = args
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = opts


WEAK_SECRETS = {"dev-only-not-secret", "test-secret", "change-me", "changeme", "secret"}


def _check_production_config(app, config_name):
    if config_name != "production":
        # A hosting platform is always production: never run the development or test settings there.
        if os.environ.get("RENDER") and not app.config.get("TESTING_ON_HOST"):
            raise RuntimeError("OIMS_ENV must be 'production' on the server")
        return
    missing = [k for k in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI") if not app.config.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment configuration: {', '.join(missing)}")
    if len(app.config["SECRET_KEY"]) < 32 or app.config["SECRET_KEY"].lower() in WEAK_SECRETS:
        raise RuntimeError("SECRET_KEY must be a random value of at least 32 characters")
    if not app.config.get("SESSION_COOKIE_SECURE"):
        raise RuntimeError("SESSION_COOKIE_SECURE must stay on in production (sign-in cookies only over https)")
    base = app.config.get("PUBLIC_BASE_URL")
    if base and not base.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL must start with https://")
    if not (app.config.get("PAYSTACK_API_BASE") or "").startswith("https://"):
        raise RuntimeError("PAYSTACK_API_BASE must start with https://")
    backend = app.config["STORAGE_BACKEND"]
    if backend == "s3" and not app.config.get("S3_BUCKET"):
        raise RuntimeError("STORAGE_BACKEND=s3 requires S3_BUCKET")
    if backend == "local" and not os.path.isabs(app.config.get("UPLOAD_ROOT") or ""):
        raise RuntimeError("Set UPLOAD_ROOT to an absolute path on a persistent disk, or use STORAGE_BACKEND=s3")
    if backend not in ("local", "s3"):
        raise RuntimeError("STORAGE_BACKEND must be 'local' or 's3'")


PASSWORD_CHANGE_EXEMPT = {
    "account.change_password", "auth.logout", "static", "public.health",
    "pwa.manifest", "pwa.service_worker", "pwa.offline",
}
TWO_FACTOR_EXEMPT = PASSWORD_CHANGE_EXEMPT | {"account.two_factor"}


def _register_hooks(app):
    from app.security import apply_security_headers

    @app.before_request
    def reset_request_scope():
        # Never let tenant context leak from one request to the next (e.g. a shared app context).
        for key in ("tenant_id", "tenant", "membership", "permissions", "support_request", "_login_user", "my_staff",
                    "billing", "lang"):
            g.pop(key, None)

    @app.before_request
    def force_password_change():
        if (current_user.is_authenticated and current_user.must_change_password
                and request.endpoint not in PASSWORD_CHANGE_EXEMPT):
            return redirect(url_for("account.change_password"))
        if (current_user.is_authenticated and current_user.is_platform_staff and not current_user.has_2fa
                and app.config.get("REQUIRE_PLATFORM_2FA") and request.endpoint not in TWO_FACTOR_EXEMPT):
            return redirect(url_for("account.two_factor"))

    app.after_request(apply_security_headers)

    @app.context_processor
    def inject_globals():
        from app.navigation import build_nav, header_counts
        from app.rbac import can
        from app.timeutil import to_local
        return {
            "can": can,
            "build_nav": build_nav,
            "header_counts": header_counts,
            "local": to_local,
            "human_size": _human_size,
            "now_utc": _now_utc,
            "file_icon": _file_icon,
            "app_name": app.config["APP_NAME"],
            "app_full_name": app.config["APP_FULL_NAME"],
            "brand_name": app.config["BRAND_NAME"],
            "product_name": app.config["PRODUCT_NAME"],
            "platform_owner": app.config["PLATFORM_OWNER"],
            "app_version": app.config["OIMS_VERSION"],
            "tenant": g.get("tenant"),
            "support_request": g.get("support_request"),
        }


def _register_errors(app):
    def render_error(code, title, message):
        return render_template("errors/error.html", code=code, title=title, message=message), code

    app.register_error_handler(400, lambda e: render_error(400, "Bad request", "The request could not be processed. If you submitted a form, reload the page and try again."))
    app.register_error_handler(403, lambda e: render_error(403, "Access denied", "Your role does not allow this action. Ask your organization administrator if you need access."))
    app.register_error_handler(404, lambda e: render_error(404, "Not found", "This page does not exist or you do not have access to it."))
    app.register_error_handler(413, lambda e: render_error(413, "File too large", "The uploaded file is larger than allowed."))
    app.register_error_handler(429, lambda e: render_error(429, "Too many attempts", "Please wait a little and try again."))

    @app.errorhandler(500)
    def server_error(e):
        db.session.rollback()
        return render_error(500, "Something went wrong", "The error has been logged. Please try again.")

    from flask_wtf.csrf import CSRFError

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        return render_error(400, "Session expired", "Your form session expired. Reload the page and try again.")


def _human_size(n):
    n = n or 0
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024


def _file_icon(mime):
    mime = mime or ""
    if "pdf" in mime:
        return "bi-file-earmark-pdf"
    if "word" in mime or "opendocument.text" in mime:
        return "bi-file-earmark-word"
    if "sheet" in mime or "excel" in mime or mime == "text/csv":
        return "bi-file-earmark-spreadsheet"
    if "presentation" in mime or "powerpoint" in mime:
        return "bi-file-earmark-slides"
    if mime.startswith("image/"):
        return "bi-file-earmark-image"
    return "bi-file-earmark-text"


def _now_utc():
    from app.models import utcnow
    return utcnow()


def _register_template_globals(app):
    """Helpers usable everywhere, including inside imported macros."""
    from app.rbac import can
    from app.timeutil import to_local

    app.jinja_env.globals.update(
        can=can, local=to_local, human_size=_human_size, file_icon=_file_icon, now_utc=_now_utc,
        in_support=lambda: g.get("support_request") is not None)
