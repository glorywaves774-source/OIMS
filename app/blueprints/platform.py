"""HOLIDO platform administration (separate from organization workspaces)."""
from datetime import datetime, timedelta, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_, select

from app import audit
from app.extensions import db
from app.forms import (ActionForm, AssignPlanForm, PlanForm, PlatformCreateOrganizationForm,
                       PlatformStaffForm, ReasonForm, SupportRequestForm)
from app.models import (AuditLog, Membership, Organization, PlatformRole, Subscription,
                        SubscriptionPlan, SupportAccessRequest, User, utcnow)
from app.security import external_url, make_password_token, platform_required, send_email
from app.services import (STATUS_TRANSITIONS, ServiceError, approve_organization,
                          change_organization_status, platform_create_organization)

bp = Blueprint("platform", __name__, url_prefix="/platform")

ADMINS = (PlatformRole.SUPER_ADMIN, PlatformRole.PLATFORM_ADMIN)


@bp.before_request
@login_required
@platform_required()
def _guard():
    # A platform user browsing the console is never inside a tenant context.
    return None


def _page():
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


@bp.route("/")
def dashboard():
    counts = dict(db.session.execute(
        select(Organization.status, func.count()).group_by(Organization.status)).all())
    now = utcnow()
    soon = now + timedelta(days=30)
    expiring = (Subscription.query.join(Organization)
                .filter(Organization.status == Organization.ACTIVE,
                        or_(Subscription.current_period_end.between(now, soon),
                            Subscription.trial_ends_at.between(now, soon)))
                .order_by(Subscription.current_period_end).limit(10).all())
    stats = {
        "orgs_total": sum(counts.values()),
        "orgs_active": counts.get(Organization.ACTIVE, 0),
        "orgs_pending": counts.get(Organization.PENDING, 0),
        "orgs_suspended": counts.get(Organization.SUSPENDED, 0) + counts.get(Organization.DEACTIVATED, 0),
        "users_total": db.session.scalar(select(func.count(User.id))),
        "memberships_active": db.session.scalar(
            select(func.count(Membership.id)).where(Membership.status == Membership.ACTIVE)),
        "logins_24h": db.session.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.action == "auth.login", AuditLog.created_at >= now - timedelta(hours=24))),
        "failed_24h": db.session.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.action.in_(["auth.login_failed", "auth.locked"]),
            AuditLog.created_at >= now - timedelta(hours=24))),
    }
    pending = Organization.query.filter_by(status=Organization.PENDING).order_by(Organization.created_at).limit(10).all()
    live_support = [r for r in SupportAccessRequest.query.filter_by(status=SupportAccessRequest.APPROVED).all() if r.is_live()]
    recent = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(12).all()
    return render_template("platform/dashboard.html", stats=stats, pending=pending, expiring=expiring,
                           live_support=live_support, recent=recent)


# --- Organizations -----------------------------------------------------------------

@bp.route("/organizations")
def organizations():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    stmt = select(Organization).order_by(Organization.created_at.desc())
    if status in Organization.STATUSES:
        stmt = stmt.where(Organization.status == status)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Organization.name.ilike(like), Organization.email.ilike(like),
                              Organization.country.ilike(like), Organization.slug.ilike(like)))
    page = db.paginate(stmt, page=_page(), per_page=20, error_out=False)
    return render_template("platform/organizations.html", page=page, q=q, status=status,
                           statuses=Organization.STATUSES)


def _plan_choices(include_none=True):
    plans = SubscriptionPlan.query.filter_by(is_active=True).order_by(SubscriptionPlan.name).all()
    return ([(0, "No plan yet")] if include_none else []) + [(p.id, p.name) for p in plans]


@bp.route("/organizations/new", methods=["GET", "POST"])
@platform_required(*ADMINS)
def organization_new():
    form = PlatformCreateOrganizationForm()
    form.plan_id.choices = _plan_choices()
    if form.validate_on_submit():
        try:
            org, user, link = platform_create_organization(form, current_user)
            db.session.commit()
        except ServiceError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        else:
            _flash_link(link, user.email)
            flash(f"{org.name} created and activated.", "success")
            return redirect(url_for("platform.organization_detail", org_id=org.id))
    return render_template("platform/organization_form.html", form=form)


def _flash_link(link, email):
    if link:
        session["one_time_link"] = {"email": email, "link": link}


@bp.route("/organizations/<int:org_id>")
def organization_detail(org_id):
    org = db.get_or_404(Organization, org_id)
    members = (Membership.query.filter_by(organization_id=org.id)
               .join(User, Membership.user_id == User.id).order_by(User.full_name).all())
    support = (SupportAccessRequest.query.filter_by(organization_id=org.id)
               .order_by(SupportAccessRequest.created_at.desc()).limit(10).all())
    logs = (AuditLog.query.filter_by(organization_id=org.id)
            .order_by(AuditLog.created_at.desc()).limit(15).all())
    plan_form = AssignPlanForm()
    plan_form.plan_id.choices = _plan_choices(include_none=False)
    if org.subscription:
        plan_form.plan_id.data = org.subscription.plan_id
        plan_form.status.data = org.subscription.status
        plan_form.billing_cycle.data = org.subscription.billing_cycle
        if org.subscription.current_period_end:
            plan_form.current_period_end.data = org.subscription.current_period_end.strftime("%Y-%m-%d")
    allowed_actions = [a for a, (frm, _) in STATUS_TRANSITIONS.items() if org.status in frm]
    one_time = session.pop("one_time_link", None)
    return render_template("platform/organization_detail.html", org=org, members=members, support=support,
                           logs=logs, plan_form=plan_form, reason_form=ReasonForm(), action_form=ActionForm(),
                           support_form=SupportRequestForm(), allowed_actions=allowed_actions,
                           one_time=one_time, can_admin=current_user.platform_role in ADMINS)


@bp.route("/organizations/<int:org_id>/approve", methods=["POST"])
@platform_required(*ADMINS)
def organization_approve(org_id):
    org = db.get_or_404(Organization, org_id)
    if ActionForm().validate_on_submit():
        try:
            link = approve_organization(org, current_user)
            db.session.commit()
            first = Membership.query.filter_by(organization_id=org.id).first()
            _flash_link(link, first.user.email if first else "")
            flash(f"{org.name} approved and activated.", "success")
        except ServiceError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("platform.organization_detail", org_id=org.id))


@bp.route("/organizations/<int:org_id>/status/<action>", methods=["POST"])
@platform_required(*ADMINS)
def organization_status(org_id, action):
    if action not in STATUS_TRANSITIONS:
        abort(404)
    org = db.get_or_404(Organization, org_id)
    form = ReasonForm()
    if form.validate_on_submit():
        try:
            change_organization_status(org, action, form.reason.data, current_user)
            db.session.commit()
            flash(f"{org.name} is now {org.status}.", "success")
        except ServiceError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
    return redirect(url_for("platform.organization_detail", org_id=org.id))


@bp.route("/organizations/<int:org_id>/plan", methods=["POST"])
@platform_required(*ADMINS)
def organization_plan(org_id):
    org = db.get_or_404(Organization, org_id)
    form = AssignPlanForm()
    form.plan_id.choices = _plan_choices(include_none=False)
    if form.validate_on_submit():
        period_end = None
        if form.current_period_end.data:
            try:
                period_end = datetime.strptime(form.current_period_end.data, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                flash("Enter the period end as YYYY-MM-DD.", "danger")
                return redirect(url_for("platform.organization_detail", org_id=org.id))
        sub = org.subscription or Subscription(organization=org)
        old = (sub.plan.name if sub.plan else None, sub.status)
        sub.plan_id = form.plan_id.data
        sub.status = form.status.data
        sub.billing_cycle = form.billing_cycle.data
        sub.current_period_end = period_end
        db.session.add(sub)
        db.session.flush()
        audit.record("subscription.updated", f"Subscription set to {sub.plan.name} ({sub.status})", entity=sub,
                     organization_id=org.id, details={"previous": {"plan": old[0], "status": old[1]}})
        db.session.commit()
        flash("Subscription updated.", "success")
    else:
        flash("Check the subscription details.", "danger")
    return redirect(url_for("platform.organization_detail", org_id=org.id))


# --- Support access ------------------------------------------------------------------

@bp.route("/organizations/<int:org_id>/support", methods=["POST"])
def support_request(org_id):
    org = db.get_or_404(Organization, org_id)
    form = SupportRequestForm()
    if org.status != Organization.ACTIVE:
        flash("Support access is only available for active organizations.", "danger")
    elif form.validate_on_submit():
        req = SupportAccessRequest(organization_id=org.id, requested_by_id=current_user.id,
                                   reason=form.reason.data, duration_minutes=form.duration_minutes.data)
        db.session.add(req)
        db.session.flush()
        if not org.require_support_approval:
            req.status = SupportAccessRequest.APPROVED
            req.decided_at = req.starts_at = utcnow()
            req.expires_at = req.starts_at + timedelta(minutes=req.duration_minutes)
            msg = "Support access granted (this organization does not require approval)."
        else:
            msg = "Support access requested. The organization's administrators must approve it."
            for m in Membership.query.filter_by(organization_id=org.id, status=Membership.ACTIVE).all():
                if m.role and m.role.is_admin:
                    send_email(m.user.email, "HOLIDO support access request",
                               f"{current_user.full_name} (HOLIDO) requests read-only access to {org.name} "
                               f"for {req.duration_minutes} minutes.\nReason: {req.reason}\n"
                               f"Review: {external_url('workspace.support', org_slug=org.slug)}\n")
        audit.record("support.requested", f"Support access requested: {req.reason[:200]}", entity=req,
                     organization_id=org.id)
        db.session.commit()
        flash(msg, "success")
    else:
        flash("Give a reason of at least 10 characters.", "danger")
    return redirect(url_for("platform.organization_detail", org_id=org.id))


@bp.route("/support/<int:req_id>/enter", methods=["POST"])
def support_enter(req_id):
    req = db.get_or_404(SupportAccessRequest, req_id)
    if not ActionForm().validate_on_submit():
        abort(400)
    if req.requested_by_id != current_user.id or not req.is_live():
        flash("This support access is not active.", "danger")
        return redirect(url_for("platform.organization_detail", org_id=req.organization_id))
    session["support_request_id"] = req.id
    audit.record("support.entered", "Entered workspace with support access", entity=req,
                 organization_id=req.organization_id)
    db.session.commit()
    return redirect(url_for("workspace.dashboard", org_slug=req.organization.slug))


@bp.route("/support/<int:req_id>/end", methods=["POST"])
def support_end(req_id):
    req = db.get_or_404(SupportAccessRequest, req_id)
    if not ActionForm().validate_on_submit() or req.requested_by_id != current_user.id:
        abort(403)
    if req.status == SupportAccessRequest.APPROVED:
        req.status = SupportAccessRequest.ENDED
        req.expires_at = utcnow()
    session.pop("support_request_id", None)
    audit.record("support.ended", "Support access ended", entity=req, organization_id=req.organization_id)
    db.session.commit()
    flash("Support access ended.", "info")
    return redirect(url_for("platform.organization_detail", org_id=req.organization_id))


# --- Plans ------------------------------------------------------------------------------

@bp.route("/plans")
@platform_required(*ADMINS)
def plans():
    rows = SubscriptionPlan.query.order_by(SubscriptionPlan.is_active.desc(), SubscriptionPlan.monthly_price).all()
    usage = dict(db.session.execute(select(Subscription.plan_id, func.count()).group_by(Subscription.plan_id)).all())
    return render_template("platform/plans.html", plans=rows, usage=usage)


@bp.route("/plans/new", methods=["GET", "POST"])
@bp.route("/plans/<int:plan_id>", methods=["GET", "POST"])
@platform_required(*ADMINS)
def plan_edit(plan_id=None):
    plan = db.get_or_404(SubscriptionPlan, plan_id) if plan_id else SubscriptionPlan()
    form = PlanForm(obj=plan)
    if form.validate_on_submit():
        clash = SubscriptionPlan.query.filter(SubscriptionPlan.code == form.code.data,
                                              SubscriptionPlan.id != (plan.id or 0)).first()
        if clash:
            form.code.errors.append("Another plan already uses this code.")
        else:
            form.populate_obj(plan)
            db.session.add(plan)
            db.session.flush()
            audit.record("plan.saved", f"Plan {plan.name} saved", entity=plan)
            db.session.commit()
            flash("Plan saved.", "success")
            return redirect(url_for("platform.plans"))
    return render_template("platform/plan_form.html", form=form, plan=plan)


# --- Platform staff -----------------------------------------------------------------------

@bp.route("/staff", methods=["GET", "POST"])
@platform_required(PlatformRole.SUPER_ADMIN)
def staff():
    form = PlatformStaffForm()
    one_time = None
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and user.is_platform_staff:
            flash("This person is already HOLIDO platform staff.", "warning")
        else:
            if user is None:
                user = User(email=form.email.data, full_name=form.full_name.data)
                db.session.add(user)
            user.platform_role = form.platform_role.data
            db.session.flush()
            if not user.has_password:
                link = external_url("auth.reset_password", token=make_password_token(user))
                if not send_email(user.email, "Your HOLIDO OIMS platform account",
                                  f"Hello {user.full_name},\n\nSet your password: {link}\n"):
                    one_time = {"email": user.email, "link": link}
            audit.record("platform.staff_added", f"{user.email} added as {user.platform_role_label}", entity=user)
            db.session.commit()
            flash(f"{user.full_name} added as {user.platform_role_label}.", "success")
            if not one_time:
                return redirect(url_for("platform.staff"))
            form = PlatformStaffForm(formdata=None)
    people = User.query.filter(User.platform_role.isnot(None)).order_by(User.full_name).all()
    return render_template("platform/staff.html", form=form, people=people, action_form=ActionForm(),
                           one_time=one_time)


@bp.route("/staff/<int:user_id>/<action>", methods=["POST"])
@platform_required(PlatformRole.SUPER_ADMIN)
def staff_action(user_id, action):
    user = db.get_or_404(User, user_id)
    if not ActionForm().validate_on_submit() or not user.is_platform_staff:
        abort(400)
    if user.id == current_user.id:
        flash("You cannot change your own platform access.", "danger")
        return redirect(url_for("platform.staff"))
    if action == "remove":
        if user.is_super_admin and User.query.filter_by(platform_role=PlatformRole.SUPER_ADMIN).count() <= 1:
            flash("At least one Super Admin must remain.", "danger")
            return redirect(url_for("platform.staff"))
        label = user.platform_role_label
        user.platform_role = None
        user.session_version += 1
        audit.record("platform.staff_removed", f"{user.email} removed from {label}", entity=user)
    elif action == "reset-2fa":
        user.reset_two_factor()
        audit.record("platform.staff_2fa_reset", f"Two-step sign-in reset for {user.email}", entity=user)
    elif action == "force-signout":
        user.session_version += 1
        audit.record("platform.staff_signed_out", f"{user.email} signed out of all sessions", entity=user)
    else:
        abort(404)
    db.session.commit()
    flash("Done.", "success")
    return redirect(url_for("platform.staff"))


# --- Audit -----------------------------------------------------------------------------------

@bp.route("/audit")
def audit_log():
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    org_id = request.args.get("org", type=int)
    action = (request.args.get("action") or "").strip()
    actor = (request.args.get("actor") or "").strip().lower()
    if org_id:
        stmt = stmt.where(AuditLog.organization_id == org_id)
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"{action}%"))
    if actor:
        stmt = stmt.where(AuditLog.actor_email.ilike(f"%{actor}%"))
    page = db.paginate(stmt, page=_page(), per_page=40, error_out=False)
    orgs = Organization.query.order_by(Organization.name).all()
    return render_template("platform/audit.html", page=page, orgs=orgs, org_id=org_id, action=action, actor=actor)
