"""Beneficiaries inside a programme or project: enrolment list, people reached (counted once) and
named attendance for activity sessions."""
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import or_, select

from app import audit
from app.blueprints.programmes import child, ctx, load, owner_ep, route
from app.blueprints.tenant import page_arg
from app.extensions import db
from app.forms import ActionForm
from app.meal_logic import beneficiary_scope_clause, can_register_for, can_see_beneficiary, reach
from app.models import Activity, ActivityAttendance, ActivityReport, Beneficiary, Enrollment
from app.rbac import can


@route("/<int:pid>/beneficiaries")
def beneficiaries(pid):
    prog = load(pid)
    if not can("beneficiaries.view"):
        abort(403)
    q = (request.args.get("q") or "").strip()
    col = getattr(Enrollment, prog.fk)
    stmt = (select(Beneficiary).join(Enrollment, Enrollment.beneficiary_id == Beneficiary.id)
            .where(col == prog.id, Beneficiary.status != "merged", beneficiary_scope_clause()))
    if q:
        stmt = stmt.where(or_(Beneficiary.first_name.ilike(f"%{q}%"), Beneficiary.last_name.ilike(f"%{q}%"),
                              Beneficiary.code.ilike(f"%{q}%")))
    page = db.paginate(stmt.order_by(Beneficiary.last_name, Beneficiary.first_name), page=page_arg(), per_page=40,
                       error_out=False)
    enrol = {e.beneficiary_id: e for e in Enrollment.query.filter(
        col == prog.id, Enrollment.beneficiary_id.in_([b.id for b in page.items] or [0]))}
    totals = reach(prog)
    own_only = reach(prog, include_projects=False) if prog.kind == "programme" else None
    return render_template("programmes/beneficiaries.html", page=page, enrol=enrol, q=q, totals=totals, own_only=own_only,
                           can_enrol=can_register_for(prog), **ctx(prog, "beneficiaries"))


@route("/<int:pid>/beneficiaries/enrol", methods=["POST"])
def enrol_by_code(pid):
    prog = load(pid)
    if not can_register_for(prog) or not ActionForm().validate_on_submit():
        abort(403)
    code = (request.form.get("code") or "").strip().upper()
    b = Beneficiary.query.filter_by(code=code).first()
    if b is None or b.status != "active" or not can_see_beneficiary(b):
        flash("No active beneficiary with that code that you can see. Register them first.", "danger")
    elif b.consent_state != "given":
        flash(f"{b.code} has no current consent. Record consent on their page first.", "danger")
    elif Enrollment.query.filter_by(beneficiary_id=b.id, **{prog.fk: prog.id}).first():
        flash(f"{b.code} is already enrolled.", "info")
    else:
        db.session.add(Enrollment(organization_id=g.tenant.id, beneficiary_id=b.id, enrolled_on=date.today(),
                                  enrolled_by_id=current_user.id, **{prog.fk: prog.id}))
        audit.record("beneficiary.enrolled", f"{b.code} enrolled in {prog.code}", entity=b)
        db.session.commit()
        flash(f"{b.code} enrolled.", "success")
    return redirect(url_for(owner_ep(prog, "beneficiaries"), pid=prog.id))


def _report(prog, aid, rid):
    act = child(Activity, aid, prog)
    rep = db.session.get(ActivityReport, rid)
    if rep is None or rep.activity_id != act.id:
        abort(404)
    return act, rep


@route("/<int:pid>/activities/<int:aid>/reports/<int:rid>/attendance", methods=["GET", "POST"])
def attendance(pid, aid, rid):
    """Tick who took part. Only people enrolled here, with consent, can be added."""
    prog = load(pid)
    if not can("beneficiaries.view"):
        abort(403)
    act, rep = _report(prog, aid, rid)
    present = {a.beneficiary_id for a in ActivityAttendance.query.filter_by(report_id=rep.id)}
    col = getattr(Enrollment, prog.fk)
    eligible = db.session.execute(
        select(Beneficiary).join(Enrollment, Enrollment.beneficiary_id == Beneficiary.id)
        .where(col == prog.id, Beneficiary.status == "active", beneficiary_scope_clause())
        .order_by(Beneficiary.last_name, Beneficiary.first_name)).scalars().all()
    eligible = [b for b in eligible if b.consent_state == "given" or b.id in present]
    editable = can_register_for(prog)
    if request.method == "POST":
        if not editable or not ActionForm().validate_on_submit():
            abort(403)
        chosen = {int(v) for v in request.form.getlist("beneficiary_id") if v.isdigit()}
        allowed_ids = {b.id for b in eligible}
        if not chosen <= allowed_ids:
            abort(400)
        for a in ActivityAttendance.query.filter_by(report_id=rep.id).all():
            if a.beneficiary_id in allowed_ids and a.beneficiary_id not in chosen:
                db.session.delete(a)
        for bid in chosen - present:
            db.session.add(ActivityAttendance(organization_id=g.tenant.id, report_id=rep.id, beneficiary_id=bid,
                                              recorded_by_id=current_user.id))
        audit.record("activity.attendance", f"Attendance for '{act.title}' on {rep.report_date}: {len(chosen)} people",
                     entity=act)
        db.session.commit()
        flash(f"Attendance saved: {len(chosen)} people.", "success")
        return redirect(url_for(owner_ep(prog, "activity_detail"), pid=prog.id, aid=act.id) + "#reports")
    return render_template("programmes/attendance.html", act=act, rep=rep, eligible=eligible, present=present,
                           editable=editable, **ctx(prog, "workplans"))


def attendance_summary(report_ids):
    """{report_id: {"total", "female", "male"}} for named attendance."""
    out = {}
    if not report_ids:
        return out
    rows = db.session.execute(select(ActivityAttendance.report_id, Beneficiary.sex)
                              .join(Beneficiary, Beneficiary.id == ActivityAttendance.beneficiary_id)
                              .where(ActivityAttendance.report_id.in_(report_ids))).all()
    for rid, sex in rows:
        d = out.setdefault(rid, {"total": 0, "female": 0, "male": 0})
        d["total"] += 1
        if sex in ("female", "male"):
            d[sex] += 1
    return out
