from flask import (Blueprint, current_app, flash, redirect, render_template, request, session,
                   url_for)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash

from app import audit
from app.extensions import db, limiter
from app.forms import ActionForm, ForgotPasswordForm, LoginForm, SetPasswordForm
from app.models import Membership, Organization, User
from app.security import (external_url, is_safe_next, make_password_token, password_problems,
                          read_password_token, send_email)

bp = Blueprint("auth", __name__, url_prefix="/auth")

# Used to keep response timing similar for unknown emails.
_DUMMY_HASH = "scrypt:32768:8:1$abcdefghijklmnop$" + "0" * 128
GENERIC_FAIL = "Email or password is incorrect."


def _access_problem(user):
    """Return a message if the user has nothing they may access yet."""
    if user.is_platform_staff:
        return None
    statuses = [(m.status, m.organization.status) for m in user.memberships]
    if any(ms == Membership.ACTIVE and os_ == Organization.ACTIVE for ms, os_ in statuses):
        return None
    if any(os_ == Organization.PENDING for _, os_ in statuses):
        return "Your organization's registration is awaiting approval by HOLIDO. You will be notified when it is approved."
    if any(os_ == Organization.SUSPENDED for _, os_ in statuses):
        return "Your organization's workspace is currently suspended. Please contact HOLIDO support."
    return "Your account does not currently have access to any active organization."


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute; 50 per hour", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("account.home"))
    form = LoginForm()
    if form.validate_on_submit():
        cfg = current_app.config
        user = User.query.filter_by(email=form.email.data).first()
        if user is None:
            check_password_hash(_DUMMY_HASH, form.password.data)
            audit.record("auth.login_failed", "Unknown email", details={"email": form.email.data[:255]})
            db.session.commit()
            flash(GENERIC_FAIL, "danger")
        elif user.is_locked():
            audit.record("auth.login_blocked", "Sign-in attempted while locked", entity=user, actor=user)
            db.session.commit()
            flash("This account is temporarily locked after repeated failed sign-ins. Try again later or reset your password.", "danger")
        elif not user.check_password(form.password.data) or not user.is_enabled:
            locked = user.register_failed_login(cfg["LOGIN_MAX_FAILURES"], cfg["LOGIN_LOCKOUT_MINUTES"])
            audit.record("auth.locked" if locked else "auth.login_failed",
                         "Account locked" if locked else "Wrong password", entity=user, actor=user)
            db.session.commit()
            flash(GENERIC_FAIL, "danger")
        else:
            problem = _access_problem(user)
            if problem:
                flash(problem, "warning")
            else:
                user.register_successful_login()
                session.clear()
                login_user(user, remember=form.remember.data)
                session.permanent = True
                audit.record("auth.login", "Signed in", entity=user, actor=user)
                db.session.commit()
                nxt = request.args.get("next")
                return redirect(nxt if is_safe_next(nxt) else url_for("account.home"))
    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    form = ActionForm()
    if form.validate_on_submit():
        audit.record("auth.logout", "Signed out", entity=current_user._get_current_object())
        db.session.commit()
        logout_user()
        session.clear()
        flash("You have signed out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/forgot", methods=["GET", "POST"])
@limiter.limit("5 per minute; 20 per hour", methods=["POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user is not None and user.is_enabled:
            link = external_url("auth.reset_password", token=make_password_token(user))
            send_email(user.email, "Reset your OIMS password",
                       f"Hello {user.full_name},\n\nUse this link within 24 hours to set a new password:\n{link}\n\n"
                       "If you did not ask for this, you can ignore this email.")
            audit.record("auth.password_reset_requested", "Password reset requested", entity=user, actor=user)
            db.session.commit()
        # Same response whether or not the account exists.
        flash("If an account exists for that email, a reset link has been sent.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot.html", form=form)


@bp.route("/reset/<token>", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def reset_password(token):
    user = read_password_token(token)
    if user is None:
        flash("This link is invalid or has expired. Request a new one.", "danger")
        return redirect(url_for("auth.forgot_password"))
    form = SetPasswordForm()
    if form.validate_on_submit():
        problems = password_problems(form.password.data, email=user.email, name=user.full_name)
        if problems:
            form.password.errors.extend(problems)
        else:
            first_time = not user.has_password
            user.set_password(form.password.data)
            user.must_change_password = False
            user.failed_login_count = 0
            user.locked_until = None
            for m in user.memberships:
                if m.status == Membership.INVITED:
                    m.status = Membership.ACTIVE
            audit.record("auth.password_set" if first_time else "auth.password_reset",
                         "Password set from invitation" if first_time else "Password reset by email link",
                         entity=user, actor=user)
            db.session.commit()
            if current_user.is_authenticated:
                logout_user()
            flash("Your password has been set. Please sign in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/reset.html", form=form, user=user, first_time=not user.has_password)
