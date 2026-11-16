"""Organization reports: catalogue, report pages with filters and charts, and CSV / Excel / PDF exports."""
from datetime import date

from flask import Response, abort, g, render_template, request
from sqlalchemy import select

from app import audit
from app.analytics import REPORTS, available, default_filters, run
from app.analytics_export import fmt_compact, fmt_value, to_csv, to_pdf, to_xlsx
from app.blueprints.tenant import workspace_blueprint
from app.extensions import db
from app.models import Department, Programme, Project
from app.programme_logic import can_see, visible_owner_stmt
from app.rbac import ORG, can, scope_of
from app.security import heavy_download

bp = workspace_blueprint("analytics", __name__, "/reports")


@bp.app_template_global()
def fmtv(value, fmt):
    return fmt_value(value, fmt)


@bp.app_template_global()
def fmtc(value, fmt):
    return fmt_compact(value, fmt)


@bp.app_template_global()
def bar_class(value, top, prefix="bw"):
    """Width/height class (bw-0 … bw-100) so bars need no inline styles. Non-zero values get at least 1."""
    if not value or not top:
        return f"{prefix}-0"
    return f"{prefix}-{max(1, min(100, round(float(value) / float(top) * 100)))}"


def _filters():
    f = default_filters()
    try:
        if request.args.get("from"):
            f.start = date.fromisoformat(request.args["from"])
        if request.args.get("to"):
            f.end = date.fromisoformat(request.args["to"])
    except ValueError:
        abort(400)
    if f.end < f.start:
        f.start, f.end = f.end, f.start
    ov = request.args.get("owner") or ""
    if ov:
        try:
            kind, oid = ov.split(":")
            model = {"programme": Programme, "project": Project}[kind]
        except (ValueError, KeyError):
            abort(400)
        o = db.session.get(model, int(oid)) if oid.isdigit() else None
        if o is None or o.organization_id != g.tenant.id or not (can_see("programmes.view", o)):
            abort(404)
        f.owner = o
        f.with_projects = request.args.get("projects", "1") != "0"
    dep = request.args.get("department", type=int)
    if dep:
        d = db.session.get(Department, dep)
        if d is None or d.organization_id != g.tenant.id:
            abort(404)
        f.department_id = dep
    return f


def _owner_options():
    return [(f"{o.kind}:{o.id}", f"{o.code} — {o.title[:60]}") for k in ("programme", "project")
            for o in db.session.execute(visible_owner_stmt(k).order_by("code")).scalars()]


@bp.route("/")
def index():
    reports = available()
    if not reports:
        abort(403)
    groups = {}
    for r in reports:
        groups.setdefault(r.group, []).append(r)
    return render_template("analytics/index.html", groups=groups)


def _get(key):
    r = REPORTS.get(key)
    if r is None:
        abort(404)
    if not r.allowed():
        abort(403)
    return r


@bp.route("/<key>")
def view(key):
    r = _get(key)
    f = _filters()
    data = run(r, f)
    depts = []
    if r.uses_department and scope_of("staff.records") == ORG:
        depts = db.session.execute(select(Department).where(Department.organization_id == g.tenant.id)
                                   .order_by(Department.name)).scalars().all()
    return render_template("analytics/report.html", r=r, data=data, f=f, owner_options=_owner_options() if r.uses_owner
                           else [], departments=depts, args=request.args.to_dict())


@bp.route("/<key>.<any(csv, xlsx, pdf):fmt>")
@heavy_download
def export(key, fmt):
    r = _get(key)
    f = _filters()
    data = run(r, f)
    stamp = f"{key}-{f.start}-{f.end}"
    audit.record("report.exported", f"{r.title} exported as {fmt.upper()} ({data['filters']})")
    db.session.commit()
    if fmt == "csv":
        return Response(to_csv(data, request.args.get("table")), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{stamp}.csv"'})
    if fmt == "xlsx":
        return Response(to_xlsx(data), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{stamp}.xlsx"'})
    return Response(to_pdf(data), mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{stamp}.pdf"'})


def reports_available():
    return bool(available())


__all__ = ["bp", "can", "reports_available"]
