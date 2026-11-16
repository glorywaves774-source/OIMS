"""MEAL hub: overview dashboard and data-collection forms (design, collect, verify, summarise, export)."""
import io
from collections import OrderedDict
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import func, select

from app import audit
from app.blueprints.beneficiaries import location_choices, owner_choices, owner_key, parse_owner
from app.blueprints.tenant import page_arg, workspace_blueprint
from app.extensions import db
from app.forms import ActionForm
from app.forms_meal import DataFormForm, FieldForm
from app.forms_programmes import ReviewNoteForm
from app.meal_logic import (can_see_beneficiary, consent_given_ids, profile_rows, reach, visible_beneficiaries_stmt,
                             visible_beneficiaries_where, visible_feedback_stmt)
from app.models import (Beneficiary, DataForm, Enrollment, Feedback, FormField, FormSubmission, Indicator,
                        IndicatorResult, Location, utcnow)
from app.models.meal import AGE_BANDS, SEXES
from app.programme_logic import can_do, can_see, visible_owner_stmt
from app.rbac import can
from app.security import heavy_download
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("meal", __name__, "/meal")


def _ro():
    return g.get("support_request") is not None


# ====================================================================================
# Overview
# ====================================================================================

@bp.route("/")
def dashboard():
    if not (can("meal.view") or can("beneficiaries.view") or can("feedback.view")):
        abort(403)
    data = {}
    today = date.today()
    if can("beneficiaries.view"):
        where = visible_beneficiaries_where() + [Beneficiary.status == "active"]
        rows = profile_rows(where=where)
        given = consent_given_ids(where)
        sex = {k: 0 for k in SEXES}
        ages = {b[0]: 0 for b in AGE_BANDS} | {"Unknown": 0}
        dis = no_consent = 0
        for b in rows:
            sex[b.sex] = sex.get(b.sex, 0) + 1
            ages[b.age_band] = ages.get(b.age_band, 0) + 1
            dis += 1 if b.disability else 0
            no_consent += 0 if b.id in given else 1
        month_start = today.replace(day=1)
        data["ben"] = {"total": len(rows), "sex": sex, "ages": ages, "disability": dis, "no_consent": no_consent,
                       "new_month": sum(1 for b in rows if b.registered_on >= month_start)}
        owners = [o for k in ("programme", "project")
                  for o in db.session.execute(visible_owner_stmt(k).order_by("code")).scalars()
                  if o.status != "cancelled"]
        data["reach"] = [{"o": o, "r": reach(o)} for o in owners]
    if can("meal.view"):
        pending = 0
        for k in ("programme", "project"):
            for o in db.session.execute(visible_owner_stmt(k)).scalars():
                if can_see("meal.view", o):
                    pending += IndicatorResult.query.join(Indicator).filter(
                        getattr(Indicator, o.fk) == o.id, IndicatorResult.status == "submitted").count()
        data["results_pending"] = pending
        data["subs_pending"] = sum(1 for s in FormSubmission.query.filter_by(status="submitted")
                                   if _can_view_form(s.form))
    if can("feedback.view"):
        fb = db.session.execute(visible_feedback_stmt()).scalars().all()
        open_ = [f for f in fb if f.status in Feedback.OPEN]
        closed90 = [f for f in fb if f.responded_on and f.responded_on >= today - timedelta(days=90)]
        sat = [f.satisfaction for f in fb if f.status == "closed" and f.satisfaction in ("satisfied", "partly",
                                                                                          "not_satisfied")]
        data["fb"] = {
            "total": len(fb), "open": len(open_),
            "overdue": sum(1 for f in open_ if f.due_date and f.due_date < today),
            "by_category": {k: sum(1 for f in fb if f.category == k) for k in Feedback.CATEGORIES},
            "avg_days": (round(sum((f.responded_on - f.received_on).days for f in closed90) / len(closed90), 1)
                         if closed90 else None),
            "satisfied_pct": round(100 * sat.count("satisfied") / len(sat)) if sat else None,
            # Counts only: everyone with feedback.view knows sensitive cases exist, never their content.
            "sensitive_open": db.session.scalar(select(func.count()).select_from(Feedback).where(
                Feedback.organization_id == g.tenant.id, Feedback.sensitive.is_(True),
                Feedback.status.in_(Feedback.OPEN))),
        }
    from app import dashboards
    charts = []
    if data.get("ben") and data["ben"]["total"]:
        b = data["ben"]
        charts.append(dashboards.distribution("Active beneficiaries by sex", b["sex"], SEXES))
        bands = OrderedDict((k, f"{k} years") for k, *_ in AGE_BANDS)
        bands["Unknown"] = "Age unknown"
        charts.append(dashboards.distribution("Active beneficiaries by age group", b["ages"], bands))
        reg = dashboards.registrations_per_month(visible_beneficiaries_where())
        if reg["rows"]:
            charts.append(reg)
    if data.get("fb") and data["fb"]["total"]:
        cats = {k: v.split(" (")[0] for k, v in Feedback.CATEGORIES.items()}
        charts.append(dashboards.distribution("Feedback by type", data["fb"]["by_category"], cats))
    return render_template("meal/dashboard.html", data=data, charts=charts, bands=[b[0] for b in AGE_BANDS] + ["Unknown"],
                           sexes=SEXES, categories=Feedback.CATEGORIES)


# ====================================================================================
# Data-collection forms
# ====================================================================================

def _can_view_form(f):
    return can("meal.view") and (f.owner is None or can_see("meal.view", f.owner)) \
        or (f.status == "published" and _can_collect(f))


def _can_design(f=None):
    if _ro() or not can("meal.edit"):
        return False
    if f is None or f.owner is None:
        return True
    return can_do("meal.edit", f.owner)


def _can_collect(f):
    if _ro() or f.status != "published" or not can("meal.collect"):
        return False
    return f.owner is None or can_do("meal.collect", f.owner)


def _load_form(fid):
    f = tenant_get_or_404(DataForm, fid)
    if not _can_view_form(f) and not _can_design(f):
        abort(404)
    return f


def _owner_opts(action):
    out = []
    for k in ("programme", "project"):
        for o in db.session.execute(visible_owner_stmt(k).order_by("code")).scalars():
            if can_do(action, o):
                out.append(o)
    return owner_choices(out, "— Whole organization —")


@bp.route("/forms/")
def forms():
    if not (can("meal.view") or can("meal.collect")):
        abort(403)
    rows = [f for f in DataForm.query.order_by(DataForm.status, DataForm.title).all()
            if _can_view_form(f) or _can_design(f)]
    counts = dict(db.session.execute(select(FormSubmission.form_id, func.count()).group_by(FormSubmission.form_id)).all())
    return render_template("meal/forms.html", rows=rows, counts=counts, can_design=_can_design(),
                           collect={f.id: _can_collect(f) for f in rows})


@bp.route("/forms/new", methods=["GET", "POST"])
def form_new():
    if not _can_design():
        abort(403)
    form = DataFormForm()
    form.owner.choices = _owner_opts("meal.edit")
    if request.method == "GET" and request.args.get("owner"):
        form.owner.data = request.args.get("owner")
    if form.validate_on_submit():
        owner = parse_owner(form.owner.data) if form.owner.data else None
        if owner is not None and not can_do("meal.edit", owner):
            abort(403)
        f = DataForm(organization_id=g.tenant.id, title=form.title.data, description=form.description.data or None,
                     beneficiary_link=form.beneficiary_link.data, created_by_id=current_user.id,
                     **({owner.fk: owner.id} if owner else {}))
        db.session.add(f)
        db.session.flush()
        audit.record("form.created", f"Data-collection form '{f.title}' created", entity=f)
        db.session.commit()
        flash("Form created. Add its questions, then publish it.", "success")
        return redirect(url_for("meal.form_design", fid=f.id))
    return render_template("meal/form_edit.html", form=form, f=None)


@bp.route("/forms/<int:fid>/edit", methods=["GET", "POST"])
def form_edit(fid):
    f = _load_form(fid)
    if not _can_design(f):
        abort(403)
    form = DataFormForm(obj=f)
    form.owner.choices = _owner_opts("meal.edit")
    if f.owner and owner_key(f.owner) not in dict(form.owner.choices):
        form.owner.choices.append((owner_key(f.owner), f"{f.owner.code} — {f.owner.title[:70]}"))
    if request.method == "GET":
        form.owner.data = owner_key(f.owner) if f.owner else ""
    if form.validate_on_submit():
        owner = parse_owner(form.owner.data) if form.owner.data else None
        if owner is not None and not can_do("meal.edit", owner):
            abort(403)
        has_subs = FormSubmission.query.filter_by(form_id=f.id).count() > 0
        if has_subs and (owner_key(owner) if owner else "") != (owner_key(f.owner) if f.owner else ""):
            form.owner.errors.append("This form already has answers; it cannot move to another programme or project.")
        else:
            f.title, f.description, f.beneficiary_link = form.title.data, form.description.data or None, \
                form.beneficiary_link.data
            f.programme_id = owner.id if owner and owner.kind == "programme" else None
            f.project_id = owner.id if owner and owner.kind == "project" else None
            audit.record("form.updated", f"Form '{f.title}' updated", entity=f)
            db.session.commit()
            flash("Saved.", "success")
            return redirect(url_for("meal.form_design", fid=f.id))
    return render_template("meal/form_edit.html", form=form, f=f)


def _key_for(f, label):
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:40] or "q"
    keys = {x.key for x in f.fields}
    key, n = base, 2
    while key in keys:
        key, n = f"{base}_{n}", n + 1
    return key


@bp.route("/forms/<int:fid>", methods=["GET", "POST"])
def form_design(fid):
    f = _load_form(fid)
    field_form = FieldForm()
    if request.method == "POST":
        if not _can_design(f):
            abort(403)
        if f.status != "draft":
            flash("Questions can only be changed while the form is a draft.", "warning")
            return redirect(url_for("meal.form_design", fid=f.id))
        if field_form.validate_on_submit():
            opts = [o.strip() for o in (field_form.options.data or "").splitlines() if o.strip()] \
                if field_form.field_type.data in ("choice", "multi") else None
            last = max([x.sort_order for x in f.fields] or [0])
            f.fields.append(FormField(organization_id=g.tenant.id, key=_key_for(f, field_form.label.data),
                                      label=field_form.label.data, help_text=field_form.help_text.data or None,
                                      field_type=field_form.field_type.data, options=opts,
                                      required=field_form.required.data, sort_order=last + 1))
            db.session.commit()
            flash("Question added.", "success")
            return redirect(url_for("meal.form_design", fid=f.id) + "#questions")
    return render_template("meal/form_design.html", f=f, field_form=field_form, action_form=ActionForm(),
                           can_design=_can_design(f), can_collect=_can_collect(f),
                           n_subs=FormSubmission.query.filter_by(form_id=f.id).count(), types=FormField.TYPES)


@bp.route("/forms/<int:fid>/fields/<int:qid>/<any(up, down, delete):action>", methods=["POST"])
def field_action(fid, qid, action):
    f = _load_form(fid)
    if not _can_design(f) or f.status != "draft" or not ActionForm().validate_on_submit():
        abort(403)
    q = tenant_get_or_404(FormField, qid)
    if q.form_id != f.id:
        abort(404)
    fields = list(f.fields)
    i = fields.index(q)
    if action == "delete":
        f.fields.remove(q)
    else:
        j = i - 1 if action == "up" else i + 1
        if 0 <= j < len(fields):
            fields[i], fields[j] = fields[j], fields[i]
            for n, x in enumerate(fields, 1):
                x.sort_order = n
    db.session.commit()
    return redirect(url_for("meal.form_design", fid=f.id) + "#questions")


@bp.route("/forms/<int:fid>/<any(publish, close, reopen, draft):action>", methods=["POST"])
def form_status(fid, action):
    f = _load_form(fid)
    if not _can_design(f) or not ActionForm().validate_on_submit():
        abort(403)
    if action == "publish":
        if not f.fields:
            flash("Add at least one question before publishing.", "danger")
            return redirect(url_for("meal.form_design", fid=f.id))
        f.status, f.published_at = "published", utcnow()
    elif action == "close":
        f.status = "closed"
    elif action == "reopen":
        f.status = "published"
    elif action == "draft":
        if FormSubmission.query.filter_by(form_id=f.id).count():
            flash("This form already has answers, so its questions can no longer change. Make a new form instead.",
                  "warning")
            return redirect(url_for("meal.form_design", fid=f.id))
        f.status = "draft"
    audit.record(f"form.{action}", f"Form '{f.title}' is now {f.status}", entity=f)
    db.session.commit()
    flash(f"Form is now {f.status}.", "success")
    return redirect(url_for("meal.form_design", fid=f.id))


def _parse_answers(f, data):
    answers, errors = {}, {}
    for q in f.fields:
        name = f"q_{q.key}"
        if q.field_type == "multi":
            vals = [v for v in data.getlist(name) if v in (q.options or [])]
            if len(vals) != len(data.getlist(name)):
                errors[q.key] = "Choose from the list."
            if q.required and not vals:
                errors[q.key] = "Choose at least one."
            if vals:
                answers[q.key] = vals
            continue
        raw = (data.get(name) or "").strip()
        if not raw:
            if q.required:
                errors[q.key] = "This answer is required."
            continue
        try:
            if q.field_type == "number":
                v = Decimal(raw.replace(",", ""))
                answers[q.key] = float(v)
            elif q.field_type == "integer":
                answers[q.key] = int(raw)
            elif q.field_type == "date":
                answers[q.key] = date.fromisoformat(raw).isoformat()
            elif q.field_type == "choice":
                if raw not in (q.options or []):
                    raise ValueError
                answers[q.key] = raw
            elif q.field_type == "yes_no":
                if raw not in ("yes", "no"):
                    raise ValueError
                answers[q.key] = raw
            else:
                answers[q.key] = raw[:8000 if q.field_type == "long_text" else 500]
        except (ValueError, InvalidOperation):
            errors[q.key] = {"number": "Enter a number.", "integer": "Enter a whole number.",
                             "date": "Enter a date."}.get(q.field_type, "Choose from the list.")
    return answers, errors


@bp.route("/forms/<int:fid>/collect", methods=["GET", "POST"])
def collect(fid):
    f = _load_form(fid)
    if not _can_collect(f):
        abort(403)
    from werkzeug.datastructures import MultiDict
    values, errors, ben_error = MultiDict(), {}, None
    if request.method == "POST":
        if not ActionForm().validate_on_submit():
            abort(400)
        values = request.form
        answers, errors = _parse_answers(f, request.form)
        try:
            collected_on = date.fromisoformat(request.form.get("collected_on") or "")
        except ValueError:
            collected_on, errors["_date"] = None, "Enter the date of collection."
        if collected_on and collected_on > date.today():
            errors["_date"] = "The date cannot be in the future."
        ben = None
        code = (request.form.get("beneficiary_code") or "").strip().upper()
        if code and f.beneficiary_link != "none":
            ben = Beneficiary.query.filter_by(code=code).first()
            if ben is None or ben.status == "merged" or not can_see_beneficiary(ben):
                ben_error = "No beneficiary with that code that you can see."
            elif ben.consent_state != "given":
                ben_error = "This person has no current consent; their answers cannot be recorded."
            elif f.owner and not Enrollment.query.filter_by(beneficiary_id=ben.id, **{f.owner.fk: f.owner.id}).first():
                ben_error = f"This person is not enrolled in {f.owner.code}."
        elif f.beneficiary_link == "required":
            ben_error = "Enter the beneficiary's code."
        loc = request.form.get("location_id", type=int)
        if loc:
            tenant_get_or_404(Location, loc)
        if not errors and not ben_error:
            s = FormSubmission(organization_id=g.tenant.id, form_id=f.id, beneficiary_id=ben.id if ben else None,
                               location_id=loc or None, collected_on=collected_on, collected_by_id=current_user.id,
                               answers=answers)
            db.session.add(s)
            db.session.flush()
            audit.record("form.submission", f"Answers recorded for '{f.title}'", entity=s)
            db.session.commit()
            flash("Answers saved. You can record the next one.", "success")
            return redirect(url_for("meal.collect", fid=f.id))
        flash("Some answers need attention.", "danger")
    return render_template("meal/collect.html", f=f, values=values, errors=errors, ben_error=ben_error,
                           locations=location_choices(), today=date.today(), action_form=ActionForm())


def _visible_subs(f):
    q = FormSubmission.query.filter_by(form_id=f.id)
    if not (can("meal.view") and (f.owner is None or can_see("meal.view", f.owner))):
        q = q.filter(FormSubmission.collected_by_id == current_user.id)
    return q


@bp.route("/forms/<int:fid>/answers")
def submissions(fid):
    f = _load_form(fid)
    status = request.args.get("status") or ""
    q = _visible_subs(f)
    if status in FormSubmission.STATUSES:
        q = q.filter(FormSubmission.status == status)
    page = q.order_by(FormSubmission.collected_on.desc(), FormSubmission.id.desc()).paginate(
        page=page_arg(), per_page=30, error_out=False)
    can_review = _can_design(f)
    return render_template("meal/submissions.html", f=f, page=page, status=status, can_review=can_review,
                           note_form=ReviewNoteForm(), summary=_summary(f), show_names=can("beneficiaries.view"))


def _summary(f):
    subs = [s for s in _visible_subs(f).filter(FormSubmission.status != "rejected").all()]
    out = []
    for q in f.fields:
        vals = [s.answers.get(q.key) for s in subs if s.answers.get(q.key) not in (None, "", [])]
        row = {"q": q, "answered": len(vals), "of": len(subs)}
        if q.field_type in ("choice", "yes_no", "multi"):
            opts = q.options if q.field_type != "yes_no" else ["yes", "no"]
            counts = {o: 0 for o in opts}
            for v in vals:
                for x in (v if isinstance(v, list) else [v]):
                    counts[x] = counts.get(x, 0) + 1
            row["counts"] = counts
        elif q.field_type in ("number", "integer") and vals:
            nums = [float(v) for v in vals]
            row.update(total=sum(nums), average=round(sum(nums) / len(nums), 1), low=min(nums), high=max(nums))
        out.append(row)
    return {"rows": out, "n": len(subs)}


@bp.route("/forms/<int:fid>/answers/<int:sid>/<any(verify, reject):action>", methods=["POST"])
def review(fid, sid, action):
    f = _load_form(fid)
    s = tenant_get_or_404(FormSubmission, sid)
    if s.form_id != f.id:
        abort(404)
    if not _can_design(f):
        abort(403)
    form = ReviewNoteForm()
    if not form.validate_on_submit() or s.status != "submitted":
        abort(400)
    if s.collected_by_id == current_user.id:
        flash("Someone other than the data collector must check these answers.", "danger")
    elif action == "reject" and not form.note.data:
        flash("Say why the answers are rejected.", "danger")
    else:
        s.status = "verified" if action == "verify" else "rejected"
        s.reviewed_by_id, s.reviewed_at, s.review_note = current_user.id, utcnow(), form.note.data or None
        audit.record(f"form.submission_{action}", f"Answers #{s.id} for '{f.title}' {s.status}", entity=s)
        db.session.commit()
        flash("Answers checked." if action == "verify" else "Answers rejected.", "success")
    return redirect(url_for("meal.submissions", fid=f.id, status=request.args.get("status", "")))


@bp.route("/forms/<int:fid>/answers.xlsx")
@heavy_download
def submissions_export(fid):
    import openpyxl
    from openpyxl.styles import Font
    from app.analytics_export import safe_row
    f = _load_form(fid)
    if not can("meal.view"):
        abort(403)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Answers"
    ws.append(safe_row(["#", "Date collected", "Collected by", "Location", "Beneficiary", "Status"] + [q.label for q in f.fields]))
    for c in ws[1]:
        c.font = Font(bold=True)
    for s in _visible_subs(f).order_by(FormSubmission.collected_on, FormSubmission.id):
        ws.append(safe_row([s.id, s.collected_on.isoformat(), s.collected_by.full_name if s.collected_by else "",
                   s.location.label if s.location else "", s.beneficiary.code if s.beneficiary else "", s.status] +
                  [", ".join(v) if isinstance(v, list) else v for v in (s.answers.get(q.key) for q in f.fields)]))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    audit.record("form.exported", f"Answers for '{f.title}' exported", entity=f)
    db.session.commit()
    safe = re.sub(r"[^A-Za-z0-9]+", "-", f.title).strip("-")[:40] or "form"
    return send_file(buf, as_attachment=True, download_name=f"{safe}-answers.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
