"""OIMS — Office Information Management System (HOLIDO). Application factory."""
import logging
import os

from flask import Flask, g, redirect, render_template, request, url_for
from flask_login import current_user
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config import CONFIGS
from app.extensions import csrf, db, limiter, login_manager, migrate

__version__ = "0.1.0-phase1"


def create_app(config_name=None, overrides=None):
    config_name = config_name or os.environ.get("OIMS_ENV", "production")
    app = Flask(__name__)
    app.config.from_object(CONFIGS[config_name])
    if overrides:
        app.config.update(overrides)
    app.config["OIMS_VERSION"] = __version__

    _check_production_config(app, config_name)
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

    for bp in (public_bp, auth_bp, setup_bp, account_bp, platform_bp, workspace_bp):
        app.register_blueprint(bp)

    _register_hooks(app)
    _register_errors(app)

    from app.cli import register_cli
    register_cli(app)
    return app


def _check_production_config(app, config_name):
    if config_name != "production":
        return
    missing = [k for k in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI") if not app.config.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment configuration: {', '.join(missing)}")
    if len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY must be at least 32 characters long")


PASSWORD_CHANGE_EXEMPT = {
    "account.change_password", "auth.logout", "static", "public.health",
}


def _register_hooks(app):
    from app.security import apply_security_headers

    @app.before_request
    def reset_request_scope():
        # Never let tenant context leak from one request to the next (e.g. a shared app context).
        for key in ("tenant_id", "tenant", "membership", "permissions", "support_request", "_login_user"):
            g.pop(key, None)

    @app.before_request
    def force_password_change():
        if (current_user.is_authenticated and current_user.must_change_password
                and request.endpoint not in PASSWORD_CHANGE_EXEMPT):
            return redirect(url_for("account.change_password"))

    app.after_request(apply_security_headers)

    @app.context_processor
    def inject_globals():
        from app.navigation import build_nav
        from app.rbac import can
        return {
            "can": can,
            "build_nav": build_nav,
            "app_name": app.config["APP_NAME"],
            "app_full_name": app.config["APP_FULL_NAME"],
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
