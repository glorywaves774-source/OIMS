"""First-run Kayron Super Admin setup.

Only reachable when OIMS_SETUP_TOKEN is set in the environment AND no Super Admin
exists yet. After the first Super Admin is created the route returns 404 forever.
"""
import hmac

from flask import Blueprint, abort, current_app, flash, redirect, render_template, session, url_for
from flask_login import login_user

from app import audit
from app.extensions import db, limiter
from app.forms import SetupForm
from app.models import PlatformRole, User
from app.security import password_problems
from app.services import setup_available

bp = Blueprint("setup", __name__, url_prefix="/setup")


@bp.route("/", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def first_run():
    if not setup_available():
        abort(404)
    form = SetupForm()
    if form.validate_on_submit():
        if not hmac.compare_digest(form.setup_token.data.encode(), current_app.config["SETUP_TOKEN"].encode()):
            audit.record("platform.setup_token_rejected", "Invalid setup token")
            db.session.commit()
            form.setup_token.errors.append("The setup token is not correct.")
        else:
            problems = password_problems(form.password.data, email=form.email.data)
            if problems:
                form.password.errors.extend(problems)
            elif not setup_available():  # re-check inside the request to avoid races
                abort(404)
            else:
                user = User.query.filter_by(email=form.email.data).first() or User(email=form.email.data)
                user.full_name = form.full_name.data
                user.platform_role = PlatformRole.SUPER_ADMIN
                user.is_enabled = True
                user.set_password(form.password.data)
                user.must_change_password = False
                db.session.add(user)
                db.session.flush()
                audit.record("platform.superadmin_created", "Initial Super Admin created via setup", entity=user, actor=user)
                db.session.commit()
                session.clear()
                login_user(user)
                flash("Setup complete. Remove OIMS_SETUP_TOKEN from the environment.", "success")
                return redirect(url_for("platform.dashboard"))
    return render_template("auth/setup.html", form=form)
