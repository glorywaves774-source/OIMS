from flask import (Blueprint, Response, abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required
from sqlalchemy import text

from app.extensions import db, limiter
from app.forms import OrganizationRegistrationForm
from app.models import Membership, Organization, SubscriptionPlan
from app.services import ServiceError, register_organization
from app.security import password_problems

bp = Blueprint("public", __name__)


def public_plans():
    """Plans anyone can choose, cheapest first (edited by Kayron in the Kayron console)."""
    return (SubscriptionPlan.query.filter_by(is_active=True, is_public=True)
            .order_by(SubscriptionPlan.monthly_price, SubscriptionPlan.name).all())


def money(amount):
    """1,500 for whole amounts, 1,499.50 otherwise."""
    return f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"


def storage(mb):
    if mb is None:
        return None
    return f"{mb // 1024:,} GB" if mb >= 1024 and mb % 1024 == 0 else f"{mb:,} MB"


@bp.app_template_global()
def plan_choice_label(plan):
    return f"{plan.name} · {plan.currency} {money(plan.monthly_price)} a month"


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("account.home"))
    return render_template("public/index.html", plans=public_plans(), money=money, storage=storage)


@bp.route("/language", methods=["POST"])
@limiter.limit("30 per minute")
def set_language():
    """Switch between English and French; kept for the person, or in a cookie for visitors."""
    from flask import request
    from app.i18n import COOKIE, LANGUAGES
    from app.security import is_safe_next
    lang = request.form.get("lang")
    if lang not in LANGUAGES:
        abort(400)
    if current_user.is_authenticated:
        current_user.language = lang
        db.session.commit()
    nxt = request.form.get("next")
    resp = redirect(nxt if is_safe_next(nxt) else url_for("public.index"))
    resp.set_cookie(COOKIE, lang, max_age=365 * 24 * 3600, samesite="Lax", httponly=True,
                    secure=current_app.config.get("SESSION_COOKIE_SECURE", True))
    return resp


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
    plans = public_plans()
    form.plan_id.choices = [(0, "Decide later with Kayron")] + [(p.id, plan_choice_label(p)) for p in plans]
    chosen = request.args.get("plan", type=int)
    if request.method == "GET" and chosen in {p.id for p in plans}:
        form.plan_id.data = chosen
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
