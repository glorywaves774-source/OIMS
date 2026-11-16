from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, url_for)
from flask_login import current_user, login_required
from sqlalchemy import text

from app.extensions import db, limiter
from app.forms import OrganizationRegistrationForm
from app.models import Membership, Organization, SubscriptionPlan
from app.services import ServiceError, register_organization
from app.security import password_problems

bp = Blueprint("public", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("account.home"))
    return render_template("public/index.html")


@bp.route("/healthz")
def health():
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database="ok")   # no version number: nothing useful for attackers
    except Exception:  # pragma: no cover - exercised only when the DB is down
        db.session.rollback()
        return jsonify(status="error", database="unreachable"), 503


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if not current_app.config["ALLOW_PUBLIC_REGISTRATION"]:
        abort(404)
    form = OrganizationRegistrationForm()
    plans = SubscriptionPlan.query.filter_by(is_active=True, is_public=True).order_by(SubscriptionPlan.monthly_price).all()
    form.plan_id.choices = [(0, "Decide later with Kayron")] + [(p.id, p.name) for p in plans]
    if form.validate_on_submit():
        problems = password_problems(form.password.data, email=form.admin_email.data)
        if problems:
            for p in problems:
                form.password.errors.append(p)
        else:
            try:
                register_organization(form)
                db.session.commit()
                return render_template("public/registered.html", org_name=form.name.data)
            except ServiceError as exc:
                db.session.rollback()
                flash(str(exc), "danger")
    return render_template("public/register.html", form=form, plans=plans)


@bp.route("/logo/<slug>")
@login_required
def logo(slug):
    org = Organization.query.filter_by(slug=slug).first_or_404()
    allowed = current_user.is_platform_staff or Membership.query.filter_by(
        user_id=current_user.id, organization_id=org.id).first() is not None
    if not allowed or not org.logo_data:
        abort(404)
    resp = Response(org.logo_data, mimetype=org.logo_mime)
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp
