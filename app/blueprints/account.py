from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from app import audit
from app.extensions import db
from app.forms import ChangePasswordForm, ProfileForm
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
