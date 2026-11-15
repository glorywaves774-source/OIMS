"""Programmes: registration, planning, results, activities, milestones and monitoring."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from app import audit
from app.blueprints.people import department_choices
from app.blueprints.tenant import is_member, member_choices, page_arg, workspace_blueprint
from app.extensions import db
from app.forms import ActionForm
from app.forms_programmes import (ActivityForm, ActivityReportForm, EvaluationForm, IndicatorForm, LearningForm,
                                  MilestoneForm, PlanningForm, ProgrammeForm, ProgressForm, ResponseForm,
                                  ResultEntryForm, ResultForm, ReviewNoteForm, StatusForm, TargetForm, TeamForm,
                                  VisitForm, WorkplanForm)
from app.models import (Activity, ActivityReport, BudgetLine, Department, Evaluation, Expenditure, Indicator,
                        IndicatorResult, IndicatorTarget, LearningItem, Location, Milestone, MonitoringVisit,
                        Programme, ProgrammeReport, ProgrammeTeamMember, ResultNode, Workplan, utcnow)
from app.notify import next_reference, notify
from app.programme_logic import (achievement, activity_counts, allowed, can_do, finance_summary, holders,
                                 indicator_actual, indicator_rows, overlapping_result, timeline,
                                 visible_programmes_stmt)
from app.rbac import can, require_permission
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("programmes", __name__, "/programmes")


# --- helpers -------------------------------------------------------------------------------

def load(pid):
    prog = tenant_get_or_404(Programme, pid)
    if not (can("programmes.view") and allowed("programmes.view", prog)):
        abort(404)
    g.programme = prog
    return prog


def need(code, prog):
    if not can_do(code, prog):
        abort(403)


def child(model, obj_id, prog):
    obj = tenant_get_or_404(model, obj_id)
    if getattr(obj, "programme_id", None) != prog.id:
        abort(404)
    return obj


def location_choices(blank="— None —"):
    return [(0, blank)] + [(loc.id, loc.label) for loc in Location.query.filter_by(
        organization_id=g.tenant.id, is_active=True).order_by(Location.name)]


def result_choices(prog, levels=None, blank="— None —"):
    q = ResultNode.query.filter_by(programme_id=prog.id)
    if levels:
        q = q.filter(ResultNode.level.in_(levels))
    rows = sorted(q.all(), key=lambda r: (ResultNode.ORDER.index(r.level), r.code or "", r.id))
    return [(0, blank)] + [(r.id, f"{r.code + ' ' if r.code else ''}{r.statement[:90]}") for r in rows]


def ctx(prog, tab):
    """Common template context for the programme pages."""
    return {"prog": prog, "tab": tab, "action_form": ActionForm(),
            "p_see": {c: can(c) and allowed(c, prog) for c in ("meal.view", "finance.view", "reports.view")},
            "p_can": {c: can_do(c, prog) for c in (
                "programmes.edit", "programmes.manage", "meal.collect", "meal.edit", "finance.view",
                "finance.record", "finance.approve", "reports.view", "reports.create", "reports.approve")}}


# ====================================================================================
# Register & list
# ====================================================================================

@bp.route("/")
@require_permission("programmes.view")
def index():
    q = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    sector = request.args.get("sector") or ""
    stmt = visible_programmes_stmt()
    if status in Programme.STATUSES:
        stmt = stmt.where(Programme.status == status)
    if sector:
        stmt = stmt.where(Programme.sector == sector)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Programme.title.ilike(like), Programme.code.ilike(like), Programme.description.ilike(like)))
    page = db.paginate(stmt.order_by(Programme.created_at.desc()), page=page_arg(), per_page=20, error_out=False)
    sectors = [s for (s,) in db.session.execute(select(Programme.sector).where(
        Programme.organization_id == g.tenant.id, Programme.sector.isnot(None)).distinct().order_by(Programme.sector))]
    budgets = {p.id: finance_summary(p) for p in page.items}
    return render_template("programmes/index.html", page=page, q=q, status=status, sector=sector, sectors=sectors,
                           statuses=Programme.STATUSES, budgets=budgets)


def _setup_programme_form(form):
    form.manager_id.choices = member_choices("— Not assigned —")
    form.department_id.choices = department_choices()


def _sector_suggestions():
    return [s for (s,) in db.session.execute(select(Programme.sector).where(
        Programme.organization_id == g.tenant.id, Programme.sector.isnot(None)).distinct())] or [
        "Education", "Health", "Water, sanitation and hygiene", "Livelihoods", "Agriculture and food security",
        "Gender and women's empowerment", "Child protection", "Governance", "Climate and environment"]


@bp.route("/new", methods=["GET", "POST"])
@require_permission("programmes.create")
def new():
    form = ProgrammeForm()
    _setup_programme_form(form)
    if request.method == "GET":
        form.currency.data = g.tenant.currency
        form.manager_id.data = current_user.id
    if form.validate_on_submit():
        if form.code.data and Programme.query.filter_by(organization_id=g.tenant.id, code=form.code.data).first():
            form.code.errors.append("Another programme already uses this ID.")
        elif form.manager_id.data and not is_member(form.manager_id.data):
            abort(400)
        else:
            if form.department_id.data:
                tenant_get_or_404(Department, form.department_id.data)
            prog = Programme(organization_id=g.tenant.id, created_by_id=current_user.id,
                             code=form.code.data or next_reference("PRG").replace("/0", "/", 1))
            _apply_profile(prog, form)
            db.session.add(prog)
            db.session.flush()
            if prog.manager_id and prog.manager_id != current_user.id:
                notify([prog.manager_id], "programme", f"You manage the programme {prog.title}", None,
                       "programmes.overview", pid=prog.id)
            audit.record("programme.created", f"Programme {prog.code} registered", entity=prog)
            db.session.commit()
            flash(f"Programme registered as {prog.code}.", "success")
            return redirect(url_for("programmes.overview", pid=prog.id))
    return render_template("programmes/form.html", form=form, prog=None, sectors=_sector_suggestions())


def _apply_profile(prog, form):
    for f in ("title", "sector", "description", "background", "rationale", "goal", "target_population",
              "geographic_coverage", "start_date", "end_date", "department_id", "currency"):
        setattr(prog, f, getattr(form, f).data or None)
    prog.currency = form.currency.data
    prog.manager_id = form.manager_id.data
    prog.approved_budget = form.approved_budget.data or 0


# ====================================================================================
# Overview, profile, planning, status, team
# ====================================================================================

@bp.route("/<int:pid>")
def overview(pid):
    prog = load(pid)
    fin = finance_summary(prog) if can("finance.view") and allowed("finance.view", prog) else None
    inds = indicator_rows(prog) if can("meal.view") and allowed("meal.view", prog) else []
    acts = activity_counts(prog)
    today = date.today()
    upcoming = (Activity.query.filter(Activity.programme_id == prog.id, Activity.status.in_(Activity.OPEN))
                .order_by(Activity.planned_start.is_(None), Activity.planned_start).limit(6).all())
    milestones = Milestone.query.filter_by(programme_id=prog.id).order_by(Milestone.due_date).all()
    reports_due = (ProgrammeReport.query.filter(ProgrammeReport.programme_id == prog.id,
                                                ProgrammeReport.status != "approved")
                   .order_by(ProgrammeReport.due_date.is_(None), ProgrammeReport.due_date).limit(4).all())
    from app.blueprints.documents import attachments_for
    return render_template("programmes/overview.html", fin=fin, inds=inds, acts=acts, upcoming=upcoming,
                           milestones=milestones, reports_due=reports_due, today=today,
                           files=attachments_for("programme", prog.id), status_form=StatusForm(obj=prog),
                           **ctx(prog, "overview"))


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
def edit(pid):
    prog = load(pid)
    need("programmes.edit", prog)
    form = ProgrammeForm(obj=prog)
    _setup_programme_form(form)
    manage = can_do("programmes.manage", prog)
    if form.validate_on_submit():
        clash = Programme.query.filter(Programme.organization_id == g.tenant.id, Programme.code == form.code.data,
                                       Programme.id != prog.id).first() if form.code.data else None
        if clash:
            form.code.errors.append("Another programme already uses this ID.")
        elif form.manager_id.data != prog.manager_id and not manage:
            form.manager_id.errors.append("Only programme managers' supervisors can change the manager.")
        elif form.manager_id.data and not is_member(form.manager_id.data):
            abort(400)
        else:
            if form.department_id.data:
                tenant_get_or_404(Department, form.department_id.data)
            old_budget = prog.approved_budget
            prog.code = form.code.data or prog.code
            _apply_profile(prog, form)
            audit.record("programme.updated", f"Programme {prog.code} profile updated", entity=prog,
                         details={"approved_budget": [str(old_budget), str(prog.approved_budget)]}
                         if str(old_budget) != str(prog.approved_budget) else None)
            db.session.commit()
            flash("Programme saved.", "success")
            return redirect(url_for("programmes.overview", pid=prog.id))
    return render_template("programmes/form.html", form=form, prog=prog, sectors=_sector_suggestions(), manage=manage)


@bp.route("/<int:pid>/planning", methods=["GET", "POST"])
def planning(pid):
    prog = load(pid)
    form = PlanningForm(obj=prog)
    if request.method == "POST":
        need("programmes.edit", prog)
        if form.validate_on_submit():
            form.populate_obj(prog)
            audit.record("programme.planning_updated", f"Planning for {prog.code} updated", entity=prog)
            db.session.commit()
            flash("Planning saved.", "success")
            return redirect(url_for("programmes.planning", pid=prog.id))
    return render_template("programmes/planning.html", form=form, **ctx(prog, "planning"))


STATUS_FLOW = {
    "draft": {"planned", "cancelled"}, "planned": {"approved", "draft", "cancelled"},
    "approved": {"active", "on_hold", "cancelled"}, "active": {"on_hold", "completed", "cancelled"},
    "on_hold": {"active", "cancelled"}, "completed": {"closed", "active"}, "closed": set(), "cancelled": {"draft"},
}


@bp.route("/<int:pid>/status", methods=["POST"])
def set_status(pid):
    prog = load(pid)
    need("programmes.manage", prog)
    form = StatusForm()
    if form.validate_on_submit():
        new_status = form.status.data
        if new_status == prog.status:
            pass
        elif new_status not in STATUS_FLOW[prog.status]:
            flash(f"A {prog.status.replace('_', ' ')} programme cannot move to {new_status.replace('_', ' ')}.", "danger")
        else:
            old = prog.status
            prog.status, prog.status_note = new_status, form.note.data or None
            if new_status == "approved":
                prog.approved_by_id, prog.approved_at = current_user.id, utcnow()
            notify(prog.member_ids(), "programme", f"{prog.code} is now {new_status.replace('_', ' ')}",
                   form.note.data, "programmes.overview", pid=prog.id)
            audit.record("programme.status", f"{prog.code}: {old} → {new_status}", entity=prog)
            db.session.commit()
            flash(f"Programme is now {new_status.replace('_', ' ')}.", "success")
    return redirect(url_for("programmes.overview", pid=prog.id))


@bp.route("/<int:pid>/team", methods=["GET", "POST"])
def team(pid):
    prog = load(pid)
    form = TeamForm()
    have = {t.user_id for t in prog.team} | {prog.manager_id}
    form.user_id.choices = [(0, "— Choose —")] + [(u, n) for u, n in member_choices() if u not in have]
    if request.method == "POST":
        need("programmes.manage", prog)
        if form.validate_on_submit() and is_member(form.user_id.data):
            prog.team.append(ProgrammeTeamMember(organization_id=g.tenant.id, user_id=form.user_id.data,
                                                 role_label=form.role_label.data or None))
            notify([form.user_id.data], "programme", f"You were added to the programme {prog.title}", None,
                   "programmes.overview", pid=prog.id)
            audit.record("programme.team_added", f"Team member added to {prog.code}", entity=prog)
            db.session.commit()
            flash("Team member added.", "success")
            return redirect(url_for("programmes.team", pid=prog.id))
    return render_template("programmes/team.html", form=form, **ctx(prog, "team"))


@bp.route("/<int:pid>/team/<int:member_id>/remove", methods=["POST"])
def team_remove(pid, member_id):
    prog = load(pid)
    need("programmes.manage", prog)
    m = child(ProgrammeTeamMember, member_id, prog)
    if ActionForm().validate_on_submit():
        audit.record("programme.team_removed", f"Team member removed from {prog.code}", entity=prog)
        db.session.delete(m)
        db.session.commit()
    return redirect(url_for("programmes.team", pid=prog.id))


# ====================================================================================
# Results framework
# ====================================================================================

def _framework_tree(prog):
    nodes = ResultNode.query.filter_by(programme_id=prog.id).all()
    by_parent = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)
    for lst in by_parent.values():
        lst.sort(key=lambda n: (ResultNode.ORDER.index(n.level), n.sort_order, n.code or "", n.id))
    inds = {}
    for i in Indicator.query.filter_by(programme_id=prog.id, is_active=True):
        inds.setdefault(i.result_id, []).append(i)
    out = []

    def walk(parent_id, depth):
        for n in by_parent.get(parent_id, []):
            out.append((n, depth, inds.get(n.id, [])))
            walk(n.id, depth + 1)
    walk(None, 0)
    return out, inds.get(None, [])


@bp.route("/<int:pid>/results", methods=["GET", "POST"])
def results(pid):
    prog = load(pid)
    if not (can("meal.view") and allowed("meal.view", prog)) and not can_do("programmes.edit", prog):
        abort(403)
    form = ResultForm()
    form.parent_id.choices = result_choices(prog, blank="— Top level —")
    editable = can_do("programmes.edit", prog) or can_do("meal.edit", prog)
    if request.method == "POST":
        if not editable:
            abort(403)
        if form.validate_on_submit():
            parent = child(ResultNode, form.parent_id.data, prog) if form.parent_id.data else None
            if parent and ResultNode.ORDER.index(parent.level) >= ResultNode.ORDER.index(form.level.data):
                form.parent_id.errors.append("A result must sit under a higher-level result.")
            else:
                n = ResultNode(organization_id=g.tenant.id, programme_id=prog.id, parent_id=parent.id if parent else None,
                               level=form.level.data, code=form.code.data or None, statement=form.statement.data,
                               assumptions=form.assumptions.data or None)
                db.session.add(n)
                audit.record("programme.result_added", f"{ResultNode.LEVELS[n.level]} added to {prog.code}", entity=prog)
                db.session.commit()
                flash("Result added to the framework.", "success")
                return redirect(url_for("programmes.results", pid=prog.id))
    tree, unlinked = _framework_tree(prog)
    return render_template("programmes/results.html", form=form, tree=tree, unlinked=unlinked, editable=editable,
                           levels=ResultNode.LEVELS, **ctx(prog, "results"))


@bp.route("/<int:pid>/results/<int:rid>/edit", methods=["GET", "POST"])
def result_edit(pid, rid):
    prog = load(pid)
    if not (can_do("programmes.edit", prog) or can_do("meal.edit", prog)):
        abort(403)
    node = child(ResultNode, rid, prog)
    form = ResultForm(obj=node)
    form.parent_id.choices = [c for c in result_choices(prog, blank="— Top level —") if c[0] != node.id]
    if form.validate_on_submit():
        parent = child(ResultNode, form.parent_id.data, prog) if form.parent_id.data else None
        if parent and ResultNode.ORDER.index(parent.level) >= ResultNode.ORDER.index(form.level.data):
            form.parent_id.errors.append("A result must sit under a higher-level result.")
        else:
            node.level, node.code, node.statement = form.level.data, form.code.data or None, form.statement.data
            node.assumptions, node.parent_id = form.assumptions.data or None, parent.id if parent else None
            audit.record("programme.result_updated", f"Result updated in {prog.code}", entity=prog)
            db.session.commit()
            flash("Result updated.", "success")
            return redirect(url_for("programmes.results", pid=prog.id))
    return render_template("programmes/simple_form.html", form=form, title="Edit result",
                           back=url_for("programmes.results", pid=prog.id), **ctx(prog, "results"))


@bp.route("/<int:pid>/results/<int:rid>/delete", methods=["POST"])
def result_delete(pid, rid):
    prog = load(pid)
    if not (can_do("programmes.edit", prog) or can_do("meal.edit", prog)):
        abort(403)
    node = child(ResultNode, rid, prog)
    if ActionForm().validate_on_submit():
        if ResultNode.query.filter_by(parent_id=node.id).count():
            flash("Remove or move the results under it first.", "danger")
        else:
            audit.record("programme.result_deleted", f"Result removed from {prog.code}", entity=prog)
            db.session.delete(node)
            db.session.commit()
            flash("Result removed. Its indicators and activities are kept, unlinked.", "success")
    return redirect(url_for("programmes.results", pid=prog.id))


# ====================================================================================
# Indicators
# ====================================================================================

def _meal_view(prog):
    if not (can("meal.view") and allowed("meal.view", prog)) and not can_do("meal.collect", prog):
        abort(403)


@bp.route("/<int:pid>/indicators")
def indicators(pid):
    prog = load(pid)
    _meal_view(prog)
    return render_template("programmes/indicators.html", rows=indicator_rows(prog), **ctx(prog, "indicators"))


def _setup_indicator(form, prog):
    form.result_id.choices = result_choices(prog)
    form.responsible_id.choices = member_choices("— Not assigned —")


@bp.route("/<int:pid>/indicators/new", methods=["GET", "POST"])
@bp.route("/<int:pid>/indicators/<int:iid>/edit", methods=["GET", "POST"])
def indicator_edit(pid, iid=None):
    prog = load(pid)
    need("meal.edit", prog)
    ind = child(Indicator, iid, prog) if iid else None
    form = IndicatorForm(obj=ind)
    _setup_indicator(form, prog)
    if request.method == "GET" and ind:
        form.disaggregations.data = ind.disaggregations or []
    if form.validate_on_submit():
        if form.result_id.data:
            child(ResultNode, form.result_id.data, prog)
        creating = ind is None
        if creating:
            ind = Indicator(organization_id=g.tenant.id, programme_id=prog.id)
            db.session.add(ind)
        for f in ("code", "name", "definition", "unit", "aggregation", "direction", "baseline_value", "baseline_date",
                  "target_value", "frequency", "means_of_verification", "data_source", "result_id", "responsible_id"):
            v = getattr(form, f).data
            setattr(ind, f, v if v not in ("",) else None)
        ind.disaggregations = form.disaggregations.data or None
        db.session.flush()
        audit.record("indicator.created" if creating else "indicator.updated", f"Indicator '{ind.name[:80]}' saved",
                     entity=ind)
        db.session.commit()
        flash("Indicator saved.", "success")
        return redirect(url_for("programmes.indicator_detail", pid=prog.id, iid=ind.id))
    return render_template("programmes/indicator_form.html", form=form, ind=ind, **ctx(prog, "indicators"))


@bp.route("/<int:pid>/indicators/<int:iid>", methods=["GET", "POST"])
def indicator_detail(pid, iid):
    prog = load(pid)
    _meal_view(prog)
    ind = child(Indicator, iid, prog)
    target_form, entry_form = TargetForm(prefix="t"), ResultEntryForm(prefix="r")
    entry_form.location_id.choices = location_choices("— Whole programme —")
    breakdown_cats = {k: v for k, v in Indicator.DISAGGREGATIONS.items() if k in (ind.disaggregations or [])}
    if request.method == "POST" and request.form.get("what") == "target":
        need("meal.edit", prog)
        if target_form.validate_on_submit():
            ind.targets.append(IndicatorTarget(organization_id=g.tenant.id, period_label=target_form.period_label.data,
                                               period_start=target_form.period_start.data,
                                               period_end=target_form.period_end.data,
                                               target_value=target_form.target_value.data))
            audit.record("indicator.target_added", f"Target {target_form.period_label.data} set", entity=ind)
            db.session.commit()
            flash("Target added.", "success")
            return redirect(url_for("programmes.indicator_detail", pid=prog.id, iid=ind.id))
    if request.method == "POST" and request.form.get("what") == "result":
        need("meal.collect", prog)
        if entry_form.validate_on_submit():
            if entry_form.location_id.data:
                tenant_get_or_404(Location, entry_form.location_id.data)
            breakdown, problems = _read_breakdown(breakdown_cats, entry_form.value.data)
            clash = overlapping_result(ind, entry_form.period_start.data, entry_form.period_end.data,
                                       entry_form.location_id.data) if ind.aggregation == "sum" else None
            if clash:
                entry_form.period_start.errors.append(
                    f"A result for {clash.period_start:%d %b %Y}–{clash.period_end:%d %b %Y} already covers this period"
                    f"{' and place' if clash.location_id else ''}. Edit that result instead, so nothing is counted twice.")
            elif problems:
                entry_form.value.errors.extend(problems)
            else:
                r = IndicatorResult(organization_id=g.tenant.id, indicator_id=ind.id, reported_by_id=current_user.id,
                                    period_start=entry_form.period_start.data, period_end=entry_form.period_end.data,
                                    value=entry_form.value.data, location_id=entry_form.location_id.data,
                                    source=entry_form.source.data or None, notes=entry_form.notes.data or None,
                                    breakdown=breakdown or None)
                db.session.add(r)
                db.session.flush()
                notify([u for u in holders("meal.edit", prog) if u != current_user.id], "meal",
                       f"Result to verify: {ind.name[:80]}", f"{r.value} for {r.period_start:%d %b}–{r.period_end:%d %b %Y}",
                       "programmes.indicator_detail", pid=prog.id, iid=ind.id)
                audit.record("indicator.result_reported", f"Result {r.value} reported", entity=ind)
                db.session.commit()
                flash("Result submitted for verification.", "success")
                return redirect(url_for("programmes.indicator_detail", pid=prog.id, iid=ind.id))
    actual = indicator_actual(ind)
    return render_template("programmes/indicator_detail.html", ind=ind, actual=actual, pending_actual=indicator_actual(ind, verified_only=False),
                           pct=achievement(ind, actual), target_form=target_form, entry_form=entry_form,
                           breakdown_cats=breakdown_cats, review_form=ReviewNoteForm(), **ctx(prog, "indicators"))


def _read_breakdown(cats, total):
    """Read disaggregated values; each category's parts must add up to the total."""
    out, problems = {}, []
    from decimal import Decimal, InvalidOperation
    for cat, options in cats.items():
        parts = {}
        for i, opt in enumerate(options):
            raw = (request.form.get(f"bd_{cat}_{i}") or "").strip()
            if raw:
                try:
                    parts[opt] = float(Decimal(raw))
                except InvalidOperation:
                    problems.append(f"'{raw}' is not a number.")
        if parts:
            s = sum(parts.values())
            if total is not None and abs(s - float(total)) > 0.0001:
                problems.append(f"The {cat} breakdown adds up to {s:g}, but the result is {float(total):g}.")
            out[cat] = parts
    return out, problems


@bp.route("/<int:pid>/indicators/<int:iid>/results/<int:rid>/<action>", methods=["POST"])
def result_review(pid, iid, rid, action):
    prog = load(pid)
    ind = child(Indicator, iid, prog)
    r = tenant_get_or_404(IndicatorResult, rid)
    if r.indicator_id != ind.id:
        abort(404)
    form = ReviewNoteForm()
    if not form.validate_on_submit():
        abort(400)
    if action in ("verify", "reject"):
        need("meal.edit", prog)
        if r.reported_by_id == current_user.id:
            flash("Someone other than the person who reported a result must verify it.", "danger")
            return redirect(url_for("programmes.indicator_detail", pid=prog.id, iid=ind.id))
        r.status = "verified" if action == "verify" else "rejected"
        r.verified_by_id, r.verified_at, r.review_note = current_user.id, utcnow(), form.note.data or None
        notify([r.reported_by_id], "meal", f"Result {r.status}: {ind.name[:80]}", r.review_note,
               "programmes.indicator_detail", pid=prog.id, iid=ind.id)
    elif action == "delete":
        if not (r.reported_by_id == current_user.id and r.status == "submitted") and not can_do("meal.edit", prog):
            abort(403)
        db.session.delete(r)
    else:
        abort(404)
    audit.record(f"indicator.result_{action}", f"Result for '{ind.name[:60]}' {action}", entity=ind)
    db.session.commit()
    flash("Done.", "success")
    return redirect(url_for("programmes.indicator_detail", pid=prog.id, iid=ind.id))


@bp.route("/<int:pid>/indicators/<int:iid>/targets/<int:tid>/delete", methods=["POST"])
def target_delete(pid, iid, tid):
    prog = load(pid)
    need("meal.edit", prog)
    ind = child(Indicator, iid, prog)
    t = tenant_get_or_404(IndicatorTarget, tid)
    if t.indicator_id != ind.id or not ActionForm().validate_on_submit():
        abort(404)
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for("programmes.indicator_detail", pid=prog.id, iid=ind.id))


# ====================================================================================
# Workplans, activities, milestones
# ====================================================================================

@bp.route("/<int:pid>/workplans", methods=["GET", "POST"])
def workplans(pid):
    prog = load(pid)
    wp_form, ms_form = WorkplanForm(prefix="w"), MilestoneForm(prefix="m")
    if request.method == "POST":
        need("programmes.edit", prog)
        what = request.form.get("what")
        if what == "workplan" and wp_form.validate_on_submit():
            wp = Workplan(organization_id=g.tenant.id, programme_id=prog.id)
            wp_form.populate_obj(wp)
            db.session.add(wp)
            audit.record("programme.workplan_added", f"Workplan '{wp.title}' added to {prog.code}", entity=prog)
            db.session.commit()
            flash("Workplan added.", "success")
            return redirect(url_for("programmes.workplans", pid=prog.id))
        if what == "milestone" and ms_form.validate_on_submit():
            ms = Milestone(organization_id=g.tenant.id, programme_id=prog.id)
            ms_form.populate_obj(ms)
            db.session.add(ms)
            audit.record("programme.milestone_added", f"Milestone '{ms.title}' added to {prog.code}", entity=prog)
            db.session.commit()
            flash("Milestone added.", "success")
            return redirect(url_for("programmes.workplans", pid=prog.id) + "#milestones")
    wp_filter = request.args.get("workplan", type=int)
    q = Activity.query.filter_by(programme_id=prog.id)
    if wp_filter:
        q = q.filter_by(workplan_id=wp_filter)
    acts = q.order_by(Activity.planned_start.is_(None), Activity.planned_start, Activity.code, Activity.id).all()
    milestones = Milestone.query.filter_by(programme_id=prog.id).order_by(Milestone.due_date).all()
    plans = Workplan.query.filter_by(programme_id=prog.id).order_by(Workplan.start_date).all()
    return render_template("programmes/workplans.html", plans=plans, acts=acts, milestones=milestones,
                           wp_form=wp_form, ms_form=ms_form, wp_filter=wp_filter, today=date.today(),
                           tl=timeline(prog, acts, milestones, width=1000, label_w=300), **ctx(prog, "workplans"))


@bp.route("/<int:pid>/workplans/<int:wid>/<action>", methods=["POST"])
def workplan_action(pid, wid, action):
    prog = load(pid)
    need("programmes.manage", prog)
    wp = child(Workplan, wid, prog)
    if not ActionForm().validate_on_submit() or action not in ("approve", "reopen"):
        abort(400)
    wp.status = "approved" if action == "approve" else "draft"
    wp.approved_by_id, wp.approved_at = (current_user.id, utcnow()) if action == "approve" else (None, None)
    audit.record(f"programme.workplan_{action}", f"Workplan '{wp.title}' {wp.status}", entity=prog)
    db.session.commit()
    flash(f"Workplan {wp.status}.", "success")
    return redirect(url_for("programmes.workplans", pid=prog.id))


@bp.route("/<int:pid>/milestones/<int:mid>/<action>", methods=["POST"])
def milestone_action(pid, mid, action):
    prog = load(pid)
    need("programmes.edit", prog)
    ms = child(Milestone, mid, prog)
    if not ActionForm().validate_on_submit():
        abort(400)
    if action == "achieve":
        ms.achieved_date = date.today()
    elif action == "reopen":
        ms.achieved_date = None
    elif action == "delete":
        db.session.delete(ms)
    else:
        abort(404)
    audit.record(f"programme.milestone_{action}", f"Milestone '{ms.title}': {action}", entity=prog)
    db.session.commit()
    return redirect(url_for("programmes.workplans", pid=prog.id) + "#milestones")


def _setup_activity(form, prog):
    form.workplan_id.choices = [(0, "— None —")] + [(w.id, w.title) for w in Workplan.query.filter_by(programme_id=prog.id)]
    form.result_id.choices = result_choices(prog, levels=("output", "outcome"))
    form.location_id.choices = location_choices()
    form.responsible_id.choices = member_choices("— Not assigned —")
    form.budget_line_id.choices = [(0, "— None —")] + [
        (b.id, f"{b.code + ' ' if b.code else ''}{b.description}") for b in BudgetLine.query.filter_by(programme_id=prog.id)]


@bp.route("/<int:pid>/activities/new", methods=["GET", "POST"])
@bp.route("/<int:pid>/activities/<int:aid>/edit", methods=["GET", "POST"])
def activity_edit(pid, aid=None):
    prog = load(pid)
    need("programmes.edit", prog)
    act = child(Activity, aid, prog) if aid else None
    form = ActivityForm(obj=act)
    _setup_activity(form, prog)
    if request.method == "GET" and not act:
        form.workplan_id.data = request.args.get("workplan", type=int)
    if form.validate_on_submit():
        for model, field in ((Workplan, "workplan_id"), (ResultNode, "result_id"), (BudgetLine, "budget_line_id")):
            if getattr(form, field).data:
                child(model, getattr(form, field).data, prog)
        if form.location_id.data:
            tenant_get_or_404(Location, form.location_id.data)
        if form.responsible_id.data and not is_member(form.responsible_id.data):
            abort(400)
        creating = act is None
        old_resp = act.responsible_id if act else None
        if creating:
            act = Activity(organization_id=g.tenant.id, programme_id=prog.id)
            db.session.add(act)
        for f in ("code", "title", "description", "category", "workplan_id", "result_id", "location_id", "planned_start",
                  "planned_end", "responsible_id", "budget_line_id", "target_participants"):
            v = getattr(form, f).data
            setattr(act, f, v if v not in ("",) else None)
        act.planned_budget = form.planned_budget.data or 0
        db.session.flush()
        if act.responsible_id and act.responsible_id != old_resp:
            notify([act.responsible_id], "programme", f"Activity assigned to you: {act.title}",
                   f"{prog.code} · starts {act.planned_start:%d %b %Y}" if act.planned_start else prog.code,
                   "programmes.activity_detail", pid=prog.id, aid=act.id)
        audit.record("activity.created" if creating else "activity.updated", f"Activity '{act.title}' saved", entity=act)
        db.session.commit()
        flash("Activity saved.", "success")
        return redirect(url_for("programmes.activity_detail", pid=prog.id, aid=act.id))
    return render_template("programmes/activity_form.html", form=form, act=act, **ctx(prog, "workplans"))


def _can_update_activity(act, prog):
    return not g.get("support_request") and (act.responsible_id == current_user.id or can_do("programmes.edit", prog))


def _can_report_activity(act, prog):
    return not g.get("support_request") and (act.responsible_id == current_user.id or can_do("meal.collect", prog)
                                             or can_do("programmes.edit", prog))


@bp.route("/<int:pid>/activities/<int:aid>")
def activity_detail(pid, aid):
    prog = load(pid)
    act = child(Activity, aid, prog)
    from app.blueprints.documents import attachments_for
    rep_form = ActivityReportForm()
    rep_form.location_id.choices = location_choices()
    if not rep_form.location_id.data:
        rep_form.location_id.data = act.location_id
    spend = []
    if can("finance.view") and allowed("finance.view", prog):
        spend = Expenditure.query.filter_by(activity_id=act.id).order_by(Expenditure.spent_on.desc()).all()
    return render_template("programmes/activity_detail.html", act=act, progress_form=ProgressForm(obj=act),
                           rep_form=rep_form, files=attachments_for("activity", act.id), spend=spend,
                           can_update=_can_update_activity(act, prog), can_report=_can_report_activity(act, prog),
                           today=date.today(), **ctx(prog, "workplans"))


@bp.route("/<int:pid>/activities/<int:aid>/progress", methods=["POST"])
def activity_progress(pid, aid):
    prog = load(pid)
    act = child(Activity, aid, prog)
    if not _can_update_activity(act, prog):
        abort(403)
    form = ProgressForm()
    if form.validate_on_submit():
        old = act.status
        act.status = form.status.data
        act.progress = 100 if act.status == "completed" else (form.progress.data if form.progress.data is not None else act.progress)
        act.actual_start = form.actual_start.data or act.actual_start or (date.today() if act.status == "in_progress" else None)
        act.actual_end = form.actual_end.data or (date.today() if act.status == "completed" and not act.actual_end else act.actual_end)
        if old != act.status and prog.manager_id:
            notify([prog.manager_id], "programme", f"Activity {act.status.replace('_', ' ')}: {act.title}", None,
                   "programmes.activity_detail", pid=prog.id, aid=act.id)
        audit.record("activity.progress", f"Activity '{act.title}': {act.status}, {act.progress}%", entity=act)
        db.session.commit()
        flash("Progress updated.", "success")
    return redirect(url_for("programmes.activity_detail", pid=prog.id, aid=act.id))


@bp.route("/<int:pid>/activities/<int:aid>/report", methods=["POST"])
def activity_report(pid, aid):
    prog = load(pid)
    act = child(Activity, aid, prog)
    if not _can_report_activity(act, prog):
        abort(403)
    form = ActivityReportForm()
    form.location_id.choices = location_choices()
    if form.validate_on_submit():
        if form.location_id.data:
            tenant_get_or_404(Location, form.location_id.data)
        youth, dis = form.participants_youth.data, form.participants_disability.data
        total = (form.participants_female.data or 0) + (form.participants_male.data or 0)
        if (youth or 0) > total or (dis or 0) > total:
            flash("Young people and people with a disability are part of the total, so they cannot exceed it.", "danger")
            return redirect(url_for("programmes.activity_detail", pid=prog.id, aid=act.id) + "#report")
        rep = ActivityReport(organization_id=g.tenant.id, activity_id=act.id, submitted_by_id=current_user.id)
        form.populate_obj(rep)
        rep.participants_female, rep.participants_male = form.participants_female.data or 0, form.participants_male.data or 0
        db.session.add(rep)
        if act.status == "planned":
            act.status, act.actual_start = "in_progress", act.actual_start or rep.report_date
        notify([prog.manager_id], "programme", f"Activity report: {act.title}", f"{total} participants",
               "programmes.activity_detail", pid=prog.id, aid=act.id)
        audit.record("activity.report", f"Report for '{act.title}' on {rep.report_date}", entity=act)
        db.session.commit()
        flash("Activity report saved.", "success")
    else:
        flash("Check the report details: " + "; ".join(e for errs in form.errors.values() for e in errs), "danger")
    return redirect(url_for("programmes.activity_detail", pid=prog.id, aid=act.id) + "#reports")


# ====================================================================================
# Monitoring, evaluation & learning
# ====================================================================================

@bp.route("/<int:pid>/monitoring", methods=["GET", "POST"])
def monitoring(pid):
    prog = load(pid)
    _meal_view(prog)
    visit_form, eval_form, learn_form = VisitForm(prefix="v"), EvaluationForm(prefix="e"), LearningForm(prefix="l")
    visit_form.location_id.choices = location_choices()
    evals = Evaluation.query.filter_by(programme_id=prog.id).order_by(Evaluation.start_date.desc()).all()
    learn_form.evaluation_id.choices = [(0, "— None —")] + [(e.id, e.title) for e in evals]
    learn_form.responsible_id.choices = member_choices("— Not assigned —")
    what = request.form.get("what")
    if request.method == "POST":
        if what == "visit":
            need("meal.collect", prog)
            if visit_form.validate_on_submit():
                v = MonitoringVisit(organization_id=g.tenant.id, programme_id=prog.id, visited_by_id=current_user.id)
                visit_form.populate_obj(v)
                v.location_id = visit_form.location_id.data
                if v.location_id:
                    tenant_get_or_404(Location, v.location_id)
                db.session.add(v)
                audit.record("meal.visit", f"Monitoring visit on {v.visit_date} recorded", entity=prog)
                db.session.commit()
                flash("Monitoring visit recorded.", "success")
                return redirect(url_for("programmes.monitoring", pid=prog.id) + "#visits")
        elif what == "evaluation":
            need("meal.edit", prog)
            if eval_form.validate_on_submit():
                e = Evaluation(organization_id=g.tenant.id, programme_id=prog.id)
                eval_form.populate_obj(e)
                db.session.add(e)
                audit.record("meal.evaluation", f"Evaluation '{e.title}' recorded", entity=prog)
                db.session.commit()
                flash("Evaluation recorded.", "success")
                return redirect(url_for("programmes.monitoring", pid=prog.id) + "#evaluations")
        elif what == "learning":
            if not (can_do("meal.edit", prog) or can_do("programmes.edit", prog)):
                abort(403)
            if learn_form.validate_on_submit():
                if learn_form.evaluation_id.data:
                    child(Evaluation, learn_form.evaluation_id.data, prog)
                item = LearningItem(organization_id=g.tenant.id, programme_id=prog.id, recorded_by_id=current_user.id)
                learn_form.populate_obj(item)
                db.session.add(item)
                db.session.flush()
                if item.responsible_id:
                    notify([item.responsible_id], "meal", f"{LearningItem.KINDS[item.kind]} needs a response: {item.title}",
                           None, "programmes.monitoring", pid=prog.id)
                audit.record("meal.learning", f"{item.kind.capitalize()} '{item.title}' recorded", entity=prog)
                db.session.commit()
                flash("Saved.", "success")
                return redirect(url_for("programmes.monitoring", pid=prog.id) + "#learning")
        else:
            abort(400)
    visits = MonitoringVisit.query.filter_by(programme_id=prog.id).order_by(MonitoringVisit.visit_date.desc()).all()
    learning = LearningItem.query.filter_by(programme_id=prog.id).order_by(LearningItem.created_at.desc()).all()
    return render_template("programmes/monitoring.html", visits=visits, evals=evals, learning=learning,
                           visit_form=visit_form, eval_form=eval_form, learn_form=learn_form,
                           response_form=ResponseForm(), **ctx(prog, "monitoring"))


@bp.route("/<int:pid>/evaluations/<int:eid>/edit", methods=["GET", "POST"])
def evaluation_edit(pid, eid):
    prog = load(pid)
    need("meal.edit", prog)
    e = child(Evaluation, eid, prog)
    form = EvaluationForm(obj=e)
    if form.validate_on_submit():
        form.populate_obj(e)
        audit.record("meal.evaluation_updated", f"Evaluation '{e.title}' updated", entity=prog)
        db.session.commit()
        flash("Evaluation updated.", "success")
        return redirect(url_for("programmes.monitoring", pid=prog.id) + "#evaluations")
    from app.blueprints.documents import attachments_for
    return render_template("programmes/simple_form.html", form=form, title="Edit evaluation",
                           back=url_for("programmes.monitoring", pid=prog.id),
                           attach=("evaluation", e.id, attachments_for("evaluation", e.id)), **ctx(prog, "monitoring"))


@bp.route("/<int:pid>/learning/<int:lid>/respond", methods=["POST"])
def learning_respond(pid, lid):
    prog = load(pid)
    item = child(LearningItem, lid, prog)
    if not (can_do("programmes.manage", prog) or (item.responsible_id == current_user.id and not g.get("support_request"))):
        abort(403)
    form = ResponseForm()
    if form.validate_on_submit():
        item.response_status, item.management_response = form.response_status.data, form.management_response.data or None
        audit.record("meal.management_response", f"Management response to '{item.title}': {item.response_status}",
                     entity=prog)
        db.session.commit()
        flash("Management response saved.", "success")
    return redirect(url_for("programmes.monitoring", pid=prog.id) + "#learning")

