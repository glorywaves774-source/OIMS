"""Programme reports (narrative + figures) and PDF / Excel exports; organization registers."""
from datetime import date, datetime

from flask import Response, abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app import audit
from app.blueprints.programmes import bp, child, ctx, load, need
from app.blueprints.tenant import workspace_blueprint
from app.exporting import report_data, to_pdf, to_xlsx
from app.extensions import db
from app.forms import ActionForm
from app.forms_programmes import CategoryNameForm, DonorForm, LocationForm, ReportForm, ReviewNoteForm
from app.models import BudgetCategory, BudgetLine, Donor, FundingAgreement, Location, ProgrammeReport, utcnow
from app.notify import notify
from app.programme_logic import allowed, holders
from app.rbac import can
from app.tenancy import tenant_get_or_404


def _view(prog):
    if not (can("reports.view") and allowed("reports.view", prog)):
        abort(403)


def _setup(form):
    form.donor_id.choices = [(0, "— None —")] + [(d.id, d.name) for d in Donor.query.filter_by(
        organization_id=g.tenant.id).order_by(Donor.name)]


@bp.route("/<int:pid>/reports")
def reports(pid):
    prog = load(pid)
    _view(prog)
    rows = ProgrammeReport.query.filter_by(programme_id=prog.id).order_by(ProgrammeReport.period_end.desc()).all()
    return render_template("programmes/reports.html", rows=rows, today=date.today(), **ctx(prog, "reports"))


@bp.route("/<int:pid>/reports/new", methods=["GET", "POST"])
@bp.route("/<int:pid>/reports/<int:rid>/edit", methods=["GET", "POST"])
def report_edit(pid, rid=None):
    prog = load(pid)
    need("reports.create", prog)
    rep = child(ProgrammeReport, rid, prog) if rid else None
    if rep and rep.status == "approved":
        flash("Approved reports cannot be changed.", "warning")
        return redirect(url_for("programmes.report_view", pid=prog.id, rid=rep.id))
    form = ReportForm(obj=rep)
    _setup(form)
    if request.method == "GET" and not rep:
        t = request.args.get("type")
        if t in ProgrammeReport.TYPES:
            form.report_type.data = t
    if form.validate_on_submit():
        if form.donor_id.data:
            tenant_get_or_404(Donor, form.donor_id.data)
        creating = rep is None
        if creating:
            rep = ProgrammeReport(organization_id=g.tenant.id, programme_id=prog.id, prepared_by_id=current_user.id)
            db.session.add(rep)
        form.populate_obj(rep)
        rep.donor_id = form.donor_id.data
        if rep.status == "submitted":
            rep.status = "draft"  # editing a submitted report takes it back to draft
        db.session.flush()
        audit.record("report.saved", f"Report '{rep.title}' saved", entity=rep)
        db.session.commit()
        flash("Report saved as a draft.", "success")
        return redirect(url_for("programmes.report_view", pid=prog.id, rid=rep.id))
    return render_template("programmes/report_form.html", form=form, rep=rep, **ctx(prog, "reports"))


def _data_for(prog, rep):
    if rep.status == "approved" and rep.snapshot:
        return rep.snapshot
    return report_data(prog, rep.period_start, rep.period_end, rep)


@bp.route("/<int:pid>/reports/<int:rid>")
def report_view(pid, rid):
    prog = load(pid)
    _view(prog)
    rep = child(ProgrammeReport, rid, prog)
    return render_template("programmes/report_view.html", rep=rep, data=_data_for(prog, rep), review_form=ReviewNoteForm(),
                           **ctx(prog, "reports"))


@bp.route("/<int:pid>/reports/<int:rid>/<action>", methods=["POST"])
def report_action(pid, rid, action):
    prog = load(pid)
    rep = child(ProgrammeReport, rid, prog)
    form = ReviewNoteForm()
    if not form.validate_on_submit():
        abort(400)
    if action == "submit":
        need("reports.create", prog)
        if rep.status != "draft":
            abort(400)
        rep.status = "submitted"
        notify([u for u in holders("reports.approve", prog) if u != current_user.id], "report",
               f"Report to approve: {rep.title}", prog.code, "programmes.report_view", pid=prog.id, rid=rep.id)
    elif action in ("approve", "return"):
        need("reports.approve", prog)
        if rep.status != "submitted":
            abort(400)
        if action == "approve" and rep.prepared_by_id == current_user.id:
            flash("Someone other than the author must approve the report.", "danger")
            return redirect(url_for("programmes.report_view", pid=prog.id, rid=rep.id))
        if action == "approve":
            rep.status, rep.approved_by_id, rep.approved_at = "approved", current_user.id, utcnow()
            rep.snapshot = report_data(prog, rep.period_start, rep.period_end, rep)  # freeze the figures
        else:
            rep.status = "draft"
        notify([rep.prepared_by_id], "report", f"Report {'approved' if action == 'approve' else 'returned'}: {rep.title}",
               form.note.data, "programmes.report_view", pid=prog.id, rid=rep.id)
    elif action == "delete":
        need("reports.create", prog)
        if rep.status == "approved":
            abort(400)
        audit.record("report.deleted", f"Report '{rep.title}' deleted", entity=rep)
        db.session.delete(rep)
        db.session.commit()
        return redirect(url_for("programmes.reports", pid=prog.id))
    else:
        abort(404)
    audit.record(f"report.{action}", f"Report '{rep.title}': {rep.status}", entity=rep)
    db.session.commit()
    flash("Done.", "success")
    return redirect(url_for("programmes.report_view", pid=prog.id, rid=rep.id))


def _download(content, mimetype, filename):
    resp = Response(content, mimetype=mimetype)
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp.headers["Cache-Control"] = "private, no-store"
    return resp


def _safe_name(s):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s)[:80]


@bp.route("/<int:pid>/reports/<int:rid>/export.<fmt>")
def report_export(pid, rid, fmt):
    prog = load(pid)
    _view(prog)
    rep = child(ProgrammeReport, rid, prog)
    data = _data_for(prog, rep)
    audit.record("report.exported", f"Report '{rep.title}' exported as {fmt}", entity=rep)
    db.session.commit()
    name = _safe_name(f"{prog.code}-{rep.title}")
    if fmt == "xlsx":
        return _download(to_xlsx(data, rep.title), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         f"{name}.xlsx")
    if fmt == "pdf":
        return _download(to_pdf(data, rep.title, g.tenant.name), "application/pdf", f"{name}.pdf")
    abort(404)


@bp.route("/<int:pid>/export.<fmt>")
def quick_export(pid, fmt):
    """Status report for any period, without narrative (indicator, activity and financial figures)."""
    prog = load(pid)
    _view(prog)

    def d(name):
        try:
            return datetime.strptime(request.args.get(name, ""), "%Y-%m-%d").date()
        except ValueError:
            return None
    start, end = d("from") or prog.start_date, d("to") or date.today()
    title = f"Programme status report {start or ''} to {end}".replace("  ", " ")
    data = report_data(prog, start, end)
    audit.record("report.exported", f"{prog.code} status report exported as {fmt}", entity=prog)
    db.session.commit()
    name = _safe_name(f"{prog.code}-status-{end}")
    if fmt == "xlsx":
        return _download(to_xlsx(data, title), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         f"{name}.xlsx")
    if fmt == "pdf":
        return _download(to_pdf(data, title, g.tenant.name), "application/pdf", f"{name}.pdf")
    abort(404)


# ====================================================================================
# Organization registers: donors, locations, budget categories
# ====================================================================================

registers = workspace_blueprint("registers", __name__, "/registers")


def _can_registers():
    return can("finance.manage") or can("programmes.create") or can("meal.edit") or can("organization.manage")


@registers.route("/", methods=["GET", "POST"])
def index():
    if not (_can_registers() or can("programmes.view") or can("finance.view")):
        abort(403)
    donor_form, loc_form, cat_form = DonorForm(prefix="d"), LocationForm(prefix="l"), CategoryNameForm(prefix="c")
    what = request.form.get("what")
    ro = g.get("support_request") is not None
    if request.method == "POST":
        if what == "donor":
            if not (can("finance.manage") or can("programmes.create")) or ro:
                abort(403)
            if donor_form.validate_on_submit():
                if Donor.query.filter_by(organization_id=g.tenant.id, name=donor_form.name.data).first():
                    donor_form.name.errors.append("This donor is already registered.")
                else:
                    d = Donor(organization_id=g.tenant.id)
                    donor_form.populate_obj(d)
                    db.session.add(d)
                    audit.record("register.donor", f"Donor {d.name} added")
                    db.session.commit()
                    flash("Donor added.", "success")
                    return redirect(url_for("registers.index") + "#donors")
        elif what == "location":
            if not _can_registers() or ro:
                abort(403)
            if loc_form.validate_on_submit():
                if Location.query.filter_by(organization_id=g.tenant.id, name=loc_form.name.data,
                                            district=loc_form.district.data or None).first():
                    loc_form.name.errors.append("This location already exists.")
                else:
                    loc = Location(organization_id=g.tenant.id, country=g.tenant.country)
                    loc_form.populate_obj(loc)
                    loc.district, loc.region = loc.district or None, loc.region or None
                    db.session.add(loc)
                    audit.record("register.location", f"Location {loc.label} added")
                    db.session.commit()
                    flash("Location added.", "success")
                    return redirect(url_for("registers.index") + "#locations")
        elif what == "category":
            if not can("finance.manage") or ro:
                abort(403)
            if cat_form.validate_on_submit():
                if BudgetCategory.query.filter_by(organization_id=g.tenant.id, name=cat_form.name.data).first():
                    cat_form.name.errors.append("This category already exists.")
                else:
                    n = BudgetCategory.query.filter_by(organization_id=g.tenant.id).count()
                    db.session.add(BudgetCategory(organization_id=g.tenant.id, name=cat_form.name.data, sort_order=n + 1))
                    audit.record("register.budget_category", f"Budget category {cat_form.name.data} added")
                    db.session.commit()
                    flash("Budget category added.", "success")
                    return redirect(url_for("registers.index") + "#categories")
        else:
            abort(400)
    donors = Donor.query.filter_by(organization_id=g.tenant.id).order_by(Donor.name).all()
    funded = {d_id: n for d_id, n in db.session.query(FundingAgreement.donor_id, db.func.count()).filter(
        FundingAgreement.organization_id == g.tenant.id).group_by(FundingAgreement.donor_id)}
    locations = Location.query.filter_by(organization_id=g.tenant.id).order_by(Location.region, Location.district,
                                                                               Location.name).all()
    cats = BudgetCategory.query.filter_by(organization_id=g.tenant.id).order_by(BudgetCategory.sort_order,
                                                                               BudgetCategory.name).all()
    used = {c_id for (c_id,) in db.session.query(BudgetLine.category_id).filter(
        BudgetLine.organization_id == g.tenant.id).distinct()}
    return render_template("programmes/registers.html", donors=donors, funded=funded, locations=locations, cats=cats,
                           used=used, donor_form=donor_form, loc_form=loc_form, cat_form=cat_form,
                           action_form=ActionForm(), ro=ro)


@registers.route("/locations/<int:loc_id>/toggle", methods=["POST"])
def toggle_location(loc_id):
    if not _can_registers():
        abort(403)
    loc = tenant_get_or_404(Location, loc_id)
    if ActionForm().validate_on_submit():
        loc.is_active = not loc.is_active
        db.session.commit()
    return redirect(url_for("registers.index") + "#locations")

