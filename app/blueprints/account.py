from flask import Blueprint, current_app, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required

from app import audit
from app.extensions import db
from app.forms import (ChangePasswordForm, ProfileForm, TwoFactorDisableForm,
                       TwoFactorSetupForm)
from app.security import password_problems

bp = Blueprint("account", __name__, url_prefix="/account")


@bp.route("/home")
@login_required
def home():
    """Send each person to the right place after sign-in."""
    memberships = current_user.active_memberships()
    if current_user.is_platform_staff and not memberships:
        return redirect(url_for("platform.dashboard"))
    if len(memberships) == 1 and not current_user.is_platform_staff:
        return redirect(url_for("workspace.dashboard", org_slug=memberships[0].organization.slug))
    return redirect(url_for("account.workspaces"))


@bp.route("/workspaces")
@login_required
def workspaces():
    return render_template("account/workspaces.html", memberships=current_user.active_memberships())


@bp.route("/", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data
        current_user.phone = form.phone.data or None
        current_user.email_notifications = form.email_notifications.data
        audit.record("account.profile_updated", "Profile updated", entity=current_user._get_current_object())
        db.session.commit()
        flash("Profile saved.", "success")
        return redirect(url_for("account.profile"))
    return render_template("account/profile.html", form=form)


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        user = current_user._get_current_object()
        if not user.check_password(form.current_password.data):
            form.current_password.errors.append("Your current password is not correct.")
        elif form.password.data == form.current_password.data:
            form.password.errors.append("Choose a password different from the current one.")
        else:
            problems = password_problems(form.password.data, email=user.email, name=user.full_name)
            if problems:
                form.password.errors.extend(problems)
            else:
                user.set_password(form.password.data)
                user.must_change_password = False
                audit.record("account.password_changed", "Password changed", entity=user)
                db.session.commit()
                # session_version changed; sign the user back in with the new identifier.
                from flask_login import login_user
                login_user(user)
                flash("Password changed. Other devices have been signed out.", "success")
                return redirect(url_for("account.home"))
    return render_template("account/password.html", form=form)


# --- Two-step sign-in ------------------------------------------------------------------

def two_factor_required(user):
    return user.is_platform_staff and current_app.config.get("REQUIRE_PLATFORM_2FA")


@bp.route("/two-step", methods=["GET", "POST"])
@login_required
def two_factor():
    from app.models import utcnow
    from app.twofactor import (check_code, encrypt_secret, new_recovery_codes, new_secret, provisioning_uri,
                               qr_data_uri)

    user = current_user._get_current_object()
    codes = session.pop("new_recovery_codes", None)
    if user.has_2fa:
        return render_template("account/two_factor.html", enabled=True, codes=codes, disable_form=TwoFactorDisableForm(),
                               regen_form=TwoFactorSetupForm(prefix="r"), required=two_factor_required(user),
                               remaining=len(user.recovery_codes or []))
    secret = session.get("pending_totp_secret")
    if not secret:
        secret = new_secret()
        session["pending_totp_secret"] = secret
    form = TwoFactorSetupForm()
    if form.validate_on_submit():
        counter = check_code(secret, form.code.data)
        if counter is None:
            form.code.errors.append("That code is not correct. Make sure the time on your phone is set automatically.")
        else:
            plain, hashed = new_recovery_codes()
            user.totp_secret_enc = encrypt_secret(secret)
            user.totp_enabled_at = utcnow()
            user.totp_last_counter = counter
            user.recovery_codes = hashed
            session.pop("pending_totp_secret", None)
            session["new_recovery_codes"] = plain
            audit.record("account.2fa_enabled", "Two-step sign-in turned on", entity=user)
            db.session.commit()
            flash("Two-step sign-in is on. Save your recovery codes now.", "success")
            return redirect(url_for("account.two_factor"))
    uri = provisioning_uri(secret, user.email)
    return render_template("account/two_factor.html", enabled=False, form=form, qr=qr_data_uri(uri), secret=secret,
                           required=two_factor_required(user))


@bp.route("/two-step/recovery-codes", methods=["POST"])
@login_required
def two_factor_regenerate():
    from app.twofactor import check_code, decrypt_secret, new_recovery_codes

    user = current_user._get_current_object()
    form = TwoFactorSetupForm(prefix="r")
    if user.has_2fa and form.validate_on_submit():
        counter = check_code(decrypt_secret(user.totp_secret_enc), form.code.data, user.totp_last_counter)
        if counter is None:
            flash("That code is not correct.", "danger")
        else:
            user.totp_last_counter = counter
            plain, hashed = new_recovery_codes()
            user.recovery_codes = hashed
            session["new_recovery_codes"] = plain
            audit.record("account.2fa_recovery_regenerated", "New recovery codes created", entity=user)
            db.session.commit()
            flash("New recovery codes created. The old ones no longer work.", "success")
    return redirect(url_for("account.two_factor"))


@bp.route("/two-step/disable", methods=["POST"])
@login_required
def two_factor_disable():
    from app.twofactor import verify_user_code

    user = current_user._get_current_object()
    form = TwoFactorDisableForm()
    if two_factor_required(user):
        flash("Two-step sign-in is required for Kayron platform staff.", "danger")
    elif user.has_2fa and form.validate_on_submit():
        if not user.check_password(form.password.data) or not verify_user_code(user, form.code.data):
            flash("Your password or code is not correct.", "danger")
        else:
            user.totp_secret_enc = None
            user.totp_enabled_at = None
            user.totp_last_counter = None
            user.recovery_codes = None
            audit.record("account.2fa_disabled", "Two-step sign-in turned off", entity=user)
            db.session.commit()
            flash("Two-step sign-in is off.", "info")
    return redirect(url_for("account.two_factor"))
