"""Beneficiary register: registration with duplicate checks, consent, enrolment, services, households,
merging duplicates, anonymizing, and export."""
import io
from datetime import date

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import func, or_, select

from app import audit
from app.blueprints.tenant import page_arg, workspace_blueprint
from app.crypto import blind_index, decrypt_text, encrypt_text
from app.extensions import db
from app.forms import ActionForm
from app.forms_meal import (BeneficiaryForm, ConsentForm, EndEnrollmentForm, EnrollForm, ExitForm, HouseholdForm,
                            MergeForm, ServiceForm, WithdrawForm)
from app.meal_logic import (can_manage_beneficiary, can_register_for, can_see_beneficiary, can_see_sensitive,
                            can_update_beneficiary, enrollable_owners, possible_duplicates,
                            visible_beneficiaries_stmt)
from app.models import (Activity, ActivityAttendance, Beneficiary, ConsentRecord, Enrollment, Feedback,
                        FormSubmission, Household, Location, Programme, Project, ServiceRecord, utcnow)
from app.models.meal import AGE_BANDS, SEXES
from app.notify import next_reference
from app.rbac import can, require_permission
from app.tenancy import tenant_get_or_404

bp = workspace_blueprint("beneficiaries", __name__, "/beneficiaries")


# --- helpers ---------------------------------------------------------------------------------

def owner_key(o):
    return f"{o.kind}:{o.id}"


def parse_owner(value):
    try:
        kind, oid = (value or "").split(":")
        model = {"programme": Programme, "project": Project}[kind]
        return tenant_get_or_404(model, int(oid))
    except (ValueError, KeyError):
        abort(400)


def owner_choices(owners, blank=None):
    return ([("", blank)] if blank else []) + [(owner_key(o), f"{o.code} — {o.title[:70]}") for o in owners]


def location_choices():
    return [(0, "— None —")] + [(loc.id, loc.label) for loc in Location.query.filter_by(
        organization_id=g.tenant.id, is_active=True).order_by(Location.name)]


def household_choices():
    stmt = select(Household).where(Household.organization_id == g.tenant.id).order_by(Household.name)
    return [(0, "— None —")] + [(h.id, f"{h.code} — {h.name}") for h in db.session.execute(stmt).scalars()]


def load(bid):
    b = tenant_get_or_404(Beneficiary, bid)
    if not can_see_beneficiary(b):
        abort(404)
    if b.status == "merged" and b.merged_into_id:
        flash(f"{b.code} was merged into another record.", "info")
    return b


def _birth_year(form):
    if form.date_of_birth.data:
        return form.date_of_birth.data.year
    if form.age_estimate.data is not None:
        return date.today().year - form.age_estimate.data
    return None


def _no_consent_block(b):
    if b.consent_state != "given":
        flash("Record this person's consent first. Without current consent nothing new can be recorded "
              "about them.", "danger")
        return True
    return False


# --- register & list -------------------------------------------------------------------------

@bp.route("/")
@require_permission("beneficiaries.view")
def index():
    q = (request.args.get("q") or "").strip()
    sex = request.args.get("sex") or ""
    band = request.args.get("age") or ""
    status = request.args.get("status") or "active"
    owner_val = request.args.get("owner") or ""
    loc = request.args.get("location", type=int)
    stmt = visible_beneficiaries_stmt()
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Beneficiary.first_name.ilike(like), Beneficiary.last_name.ilike(like),
                              Beneficiary.other_names.ilike(like), Beneficiary.code.ilike(like),
                              Beneficiary.community.ilike(like)))
    if sex in SEXES:
        stmt = stmt.where(Beneficiary.sex == sex)
    if status in ("active", "inactive", "exited"):
        stmt = stmt.where(Beneficiary.status == status)
    if loc:
        stmt = stmt.where(Beneficiary.location_id == loc)
    for label, lo, hi in AGE_BANDS:
        if band == label:
            y = date.today().year
            stmt = stmt.where(Beneficiary.birth_year <= y - lo, Beneficiary.birth_year >= y - hi)
    owner = None
    if owner_val:
        owner = parse_owner(owner_val)
        col = Enrollment.project_id if owner.kind == "project" else Enrollment.programme_id
        stmt = stmt.where(Beneficiary.id.in_(select(Enrollment.beneficiary_id).where(col == owner.id)))
    page = db.paginate(stmt.order_by(Beneficiary.last_name, Beneficiary.first_name, Beneficiary.id),
                       page=page_arg(), per_page=40, error_out=False)
    from app.programme_logic import visible_owner_stmt
    owners = [o for k in ("programme", "project") for o in db.session.execute(
        visible_owner_stmt(k).order_by("code")).scalars()]
    filters = {"q": q, "sex": sex, "age": band, "status": status, "owner": owner_val, "location": loc or ""}
    return render_template("beneficiaries/index.html", page=page, filters=filters, owner_opts=owner_choices(owners),
                           locations=location_choices()[1:], bands=[b[0] for b in AGE_BANDS], sexes=SEXES,
                           can_register=can("beneficiaries.register") and not g.get("support_request"),
                           can_export=can("beneficiaries.export") and not g.get("support_request"))


def _setup(form):
    form.location_id.choices = location_choices()
    form.household_id.choices = household_choices()


def _apply(b, form, sensitive):
    b.first_name, b.last_name = form.first_name.data, form.last_name.data
    b.other_names, b.sex = form.other_names.data or None, form.sex.data
    b.location_id, b.community = form.location_id.data or None, form.community.data or None
    b.household_id = form.household_id.data or None
    b.relationship_to_head = form.relationship_to_head.data or None
    b.disability = {"yes": True, "no": False}.get(form.disability.data)
    by = _birth_year(form)
    if sensitive:
        b.date_of_birth = form.date_of_birth.data
        b.birth_year = by
        b.disability_type = form.disability_type.data or None if b.disability else None
        b.phone_enc, b.phone_index = encrypt_text(form.phone.data), blind_index(form.phone.data, "phone")
        b.id_type = form.id_type.data or None
        b.id_number_enc, b.id_number_index = encrypt_text(form.id_number.data), blind_index(form.id_number.data, "id")
        b.vulnerabilities = form.vulnerabilities.data or None
        b.notes = form.notes.data or None
    elif by is not None and b.date_of_birth is None:
        b.birth_year = by


@bp.route("/new", methods=["GET", "POST"])
@require_permission("beneficiaries.register")
def new():
    if g.get("support_request"):
        abort(403)
    form = BeneficiaryForm()
    _setup(form)
    sensitive = can("beneficiaries.sensitive")
    owners = enrollable_owners()
    enroll_choices = owner_choices(owners, "— Do not enrol now —")
    consent = ConsentForm(prefix="c")
    matches, hidden_matches = [], 0
    if request.method == "GET":
        consent.given_on.data = date.today()
    if form.validate_on_submit() and consent.validate():
        if consent.given_by.data == "self" and _birth_year(form) and date.today().year - _birth_year(form) < 18:
            consent.given_by.errors.append("For a child, consent must come from a parent, guardian or caregiver.")
        elif consent.given_by.data != "self" and not consent.guardian_name.data:
            consent.guardian_name.errors.append("Give the name of the person who consented.")
        else:
            found = possible_duplicates(form.first_name.data, form.last_name.data, _birth_year(form),
                                        form.phone.data if sensitive else None,
                                        form.id_number.data if sensitive else None)
            if found and not form.confirm_new.data:
                matches = [m for m in found if can_see_beneficiary(m)]
                hidden_matches = len(found) - len(matches)
                flash("This person may already be registered. Check the possible matches below.", "warning")
            else:
                for f in (form.household_id,):
                    if f.data:
                        tenant_get_or_404(Household, f.data)
                if form.location_id.data:
                    tenant_get_or_404(Location, form.location_id.data)
                owner = None
                ov = request.form.get("enroll_owner")
                if ov:
                    owner = parse_owner(ov)
                    if not can_register_for(owner):
                        abort(403)
                b = Beneficiary(organization_id=g.tenant.id, code=next_reference("BEN"),
                                registered_by_id=current_user.id, registered_on=date.today())
                _apply(b, form, sensitive)
                db.session.add(b)
                db.session.flush()
                db.session.add(ConsentRecord(organization_id=g.tenant.id, beneficiary_id=b.id,
                                             given_on=consent.given_on.data, given_by=consent.given_by.data,
                                             guardian_name=consent.guardian_name.data or None,
                                             purposes=consent.purposes.data, method=consent.method.data,
                                             recorded_by_id=current_user.id))
                if owner is not None:
                    db.session.add(Enrollment(organization_id=g.tenant.id, beneficiary_id=b.id,
                                              enrolled_on=date.today(), enrolled_by_id=current_user.id,
                                              **{owner.fk: owner.id}))
                if found:
                    audit.record("beneficiary.duplicate_confirmed",
                                 f"{b.code} registered after checking {len(found)} possible match(es)", entity=b)
                audit.record("beneficiary.registered", f"Beneficiary {b.code} registered", entity=b)
                db.session.commit()
                flash(f"Registered as {b.code}.", "success")
                return redirect(url_for("beneficiaries.detail", bid=b.id))
    return render_template("beneficiaries/form.html", form=form, consent=consent, b=None, sensitive=sensitive,
                           matches=matches, hidden_matches=hidden_matches, enroll_choices=enroll_choices,
                           enroll_value=request.form.get("enroll_owner", request.args.get("owner", "")))


@bp.route("/<int:bid>")
def detail(bid):
    b = load(bid)
    sensitive = can_see_sensitive(b)
    if sensitive and (b.phone_enc or b.id_number_enc or b.notes or b.date_of_birth or b.vulnerabilities):
        audit.record("beneficiary.viewed_personal", f"Personal details of {b.code} viewed", entity=b)
        db.session.commit()
    services = ServiceRecord.query.filter_by(beneficiary_id=b.id).order_by(ServiceRecord.delivered_on.desc()).all()
    attendance = (db.session.query(ActivityAttendance).filter_by(beneficiary_id=b.id).all())
    from app.models import ActivityReport
    sessions = []
    for a in attendance:
        r = db.session.get(ActivityReport, a.report_id)
        sessions.append(r)
    sessions.sort(key=lambda r: r.report_date, reverse=True)
    owners = enrollable_owners()
    enrolled = {owner_key(e.owner) for e in b.enrollments}
    enroll_form, service_form = EnrollForm(), ServiceForm(prefix="s")
    enroll_form.owner.choices = owner_choices([o for o in owners if owner_key(o) not in enrolled])
    enroll_form.enrolled_on.data = date.today()
    service_form.owner.choices = owner_choices([e.owner for e in b.enrollments
                                                if e.status == "active" and can_register_for(e.owner)])
    service_form.delivered_on.data = date.today()
    consent_form = ConsentForm(prefix="c")
    consent_form.given_on.data = date.today()
    hh_members = [m for m in b.household.members if m.id != b.id and m.status != "merged"] if b.household else []
    return render_template(
        "beneficiaries/detail.html", b=b, sensitive=sensitive, services=services, sessions=sessions,
        phone=decrypt_text(b.phone_enc) if sensitive else None,
        id_number=decrypt_text(b.id_number_enc) if sensitive else None,
        enroll_form=enroll_form, service_form=service_form, consent_form=consent_form, withdraw_form=WithdrawForm(),
        end_form=EndEnrollmentForm(), exit_form=ExitForm(obj=b), merge_form=MergeForm(), action_form=ActionForm(),
        can_update=can_update_beneficiary(b), can_manage=can_manage_beneficiary(b),
        can_reg={owner_key(e.owner): can_register_for(e.owner) for e in b.enrollments},
        hh_members=hh_members, today=date.today(),
        submissions=FormSubmission.query.filter_by(beneficiary_id=b.id).order_by(
            FormSubmission.collected_on.desc()).limit(20).all())


@bp.route("/<int:bid>/edit", methods=["GET", "POST"])
def edit(bid):
    b = load(bid)
    if not can_update_beneficiary(b) or b.anonymized_at:
        abort(403)
    sensitive = can_see_sensitive(b)
    form = BeneficiaryForm(obj=b)
    _setup(form)
    if request.method == "GET":
        form.disability.data = {True: "yes", False: "no"}.get(b.disability, "")
        if sensitive:
            form.phone.data, form.id_number.data = decrypt_text(b.phone_enc), decrypt_text(b.id_number_enc)
        if b.birth_year and not b.date_of_birth:
            form.age_estimate.data = date.today().year - b.birth_year
    matches, hidden = [], 0
    if form.validate_on_submit():
        found = possible_duplicates(form.first_name.data, form.last_name.data, _birth_year(form),
                                    form.phone.data if sensitive else None,
                                    form.id_number.data if sensitive else None, exclude_id=b.id)
        changed_identity = (form.first_name.data, form.last_name.data) != (b.first_name, b.last_name)
        if found and changed_identity and not form.confirm_new.data:
            matches = [m for m in found if can_see_beneficiary(m)]
            hidden = len(found) - len(matches)
            flash("The new details match other records. Check them below.", "warning")
        else:
            if form.household_id.data:
                tenant_get_or_404(Household, form.household_id.data)
            if form.location_id.data:
                tenant_get_or_404(Location, form.location_id.data)
            _apply(b, form, sensitive)
            audit.record("beneficiary.updated", f"Beneficiary {b.code} updated", entity=b)
            db.session.commit()
            flash("Details saved.", "success")
            return redirect(url_for("beneficiaries.detail", bid=b.id))
    return render_template("beneficiaries/form.html", form=form, consent=None, b=b, sensitive=sensitive,
                           matches=matches, hidden_matches=hidden, enroll_choices=[], enroll_value="")


# --- consent ---------------------------------------------------------------------------------

@bp.route("/<int:bid>/consent", methods=["POST"])
def consent(bid):
    b = load(bid)
    if not can_update_beneficiary(b) or b.anonymized_at:
        abort(403)
    form = ConsentForm(prefix="c")
    if form.validate_on_submit():
        if form.given_by.data == "self" and b.is_minor:
            flash("For a child, consent must come from a parent, guardian or caregiver.", "danger")
        elif form.given_by.data != "self" and not form.guardian_name.data:
            flash("Give the name of the person who consented.", "danger")
        else:
            db.session.add(ConsentRecord(organization_id=g.tenant.id, beneficiary_id=b.id, given_on=form.given_on.data,
                                         given_by=form.given_by.data, guardian_name=form.guardian_name.data or None,
                                         purposes=form.purposes.data, method=form.method.data,
                                         recorded_by_id=current_user.id))
            audit.record("beneficiary.consent", f"Consent recorded for {b.code}", entity=b)
            db.session.commit()
            flash("Consent recorded.", "success")
    else:
        flash("Consent was not saved: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
    return redirect(url_for("beneficiaries.detail", bid=b.id) + "#consent")


@bp.route("/<int:bid>/consent/withdraw", methods=["POST"])
def consent_withdraw(bid):
    b = load(bid)
    if not can_update_beneficiary(b):
        abort(403)
    c = b.current_consent
    form = WithdrawForm()
    if c is None or not form.validate_on_submit():
        abort(400)
    c.withdrawn_on, c.withdrawal_note = date.today(), form.note.data or None
    audit.record("beneficiary.consent_withdrawn", f"Consent withdrawn for {b.code}", entity=b)
    db.session.commit()
    flash("Consent withdrawn. Nothing new can be recorded about this person. Their personal details can now "
          "be anonymized.", "warning")
    return redirect(url_for("beneficiaries.detail", bid=b.id) + "#consent")


# --- enrolment & services ----------------------------------------------------------------------

@bp.route("/<int:bid>/enroll", methods=["POST"])
def enroll(bid):
    b = load(bid)
    form = EnrollForm()
    owner = parse_owner(request.form.get("owner"))
    if not can_register_for(owner) or b.status != "active":
        abort(403)
    if _no_consent_block(b):
        return redirect(url_for("beneficiaries.detail", bid=b.id))
    form.owner.choices = [(owner_key(owner), "")]
    if form.validate_on_submit():
        if Enrollment.query.filter_by(beneficiary_id=b.id, **{owner.fk: owner.id}).first():
            flash(f"Already enrolled in {owner.code}.", "info")
        else:
            db.session.add(Enrollment(organization_id=g.tenant.id, beneficiary_id=b.id,
                                      enrolled_on=form.enrolled_on.data, enrolled_by_id=current_user.id,
                                      **{owner.fk: owner.id}))
            audit.record("beneficiary.enrolled", f"{b.code} enrolled in {owner.code}", entity=b)
            db.session.commit()
            flash(f"Enrolled in {owner.code}.", "success")
    return redirect(url_for("beneficiaries.detail", bid=b.id) + "#enrolment")


@bp.route("/<int:bid>/enrollments/<int:eid>/end", methods=["POST"])
def end_enrollment(bid, eid):
    b = load(bid)
    e = tenant_get_or_404(Enrollment, eid)
    if e.beneficiary_id != b.id:
        abort(404)
    if not can_register_for(e.owner):
        abort(403)
    form = EndEnrollmentForm()
    if form.validate_on_submit():
        if form.ended_on.data < e.enrolled_on:
            flash("The end date cannot be before enrolment.", "danger")
        else:
            e.status, e.ended_on, e.end_reason = form.status.data, form.ended_on.data, form.end_reason.data or None
            audit.record("beneficiary.enrollment_ended", f"{b.code}: {e.owner.code} {e.status}", entity=b)
            db.session.commit()
            flash("Enrolment updated.", "success")
    return redirect(url_for("beneficiaries.detail", bid=b.id) + "#enrolment")


@bp.route("/<int:bid>/services", methods=["POST"])
def add_service(bid):
    b = load(bid)
    form = ServiceForm(prefix="s")
    owner = parse_owner(request.form.get("s-owner"))
    if not can_register_for(owner):
        abort(403)
    if _no_consent_block(b):
        return redirect(url_for("beneficiaries.detail", bid=b.id))
    enrol = Enrollment.query.filter_by(beneficiary_id=b.id, **{owner.fk: owner.id}).first()
    if enrol is None or enrol.status != "active":
        flash(f"Enrol the person in {owner.code} first.", "danger")
        return redirect(url_for("beneficiaries.detail", bid=b.id) + "#services")
    form.owner.choices = [(owner_key(owner), "")]
    if form.validate_on_submit():
        act = None
        if form.activity_id.data:
            act = tenant_get_or_404(Activity, form.activity_id.data)
            if getattr(act, owner.fk) != owner.id:
                abort(400)
        db.session.add(ServiceRecord(organization_id=g.tenant.id, beneficiary_id=b.id, service_type=form.service_type.data,
                                     delivered_on=form.delivered_on.data, quantity=form.quantity.data,
                                     unit=form.unit.data or None, notes=form.notes.data or None,
                                     activity_id=act.id if act else None, recorded_by_id=current_user.id,
                                     **{owner.fk: owner.id}))
        audit.record("beneficiary.service", f"{b.code}: {form.service_type.data} ({owner.code})", entity=b)
        db.session.commit()
        flash("Service recorded.", "success")
    else:
        flash("Not saved: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
    return redirect(url_for("beneficiaries.detail", bid=b.id) + "#services")


# --- status, merge, anonymize ------------------------------------------------------------------

@bp.route("/<int:bid>/status", methods=["POST"])
def set_status(bid):
    b = load(bid)
    if not can_update_beneficiary(b):
        abort(403)
    form = ExitForm()
    if form.validate_on_submit():
        if form.status.data == "exited" and not form.exit_reason.data:
            flash("Give a reason for the exit.", "danger")
        else:
            b.status, b.exit_reason = form.status.data, form.exit_reason.data or None
            audit.record("beneficiary.status", f"{b.code} is now {b.status}", entity=b)
            db.session.commit()
            flash("Status updated.", "success")
    return redirect(url_for("beneficiaries.detail", bid=b.id))


@bp.route("/<int:bid>/merge", methods=["POST"])
def merge(bid):
    """Keep this record and fold a duplicate into it; nothing is counted twice afterwards."""
    keep = load(bid)
    if not can_manage_beneficiary(keep):
        abort(403)
    form = MergeForm()
    if not form.validate_on_submit():
        abort(400)
    dup = Beneficiary.query.filter_by(code=form.duplicate_code.data.upper()).first()
    if dup is None or dup.id == keep.id or dup.status == "merged" or not can_manage_beneficiary(dup):
        flash("No other active record with that code that you can manage.", "danger")
        return redirect(url_for("beneficiaries.detail", bid=keep.id))
    have = {(e.programme_id, e.project_id) for e in keep.enrollments}
    for e in list(dup.enrollments):
        if (e.programme_id, e.project_id) in have:
            db.session.delete(e)
        else:
            e.beneficiary_id = keep.id
    attended = {a.report_id for a in ActivityAttendance.query.filter_by(beneficiary_id=keep.id)}
    for a in ActivityAttendance.query.filter_by(beneficiary_id=dup.id).all():
        if a.report_id in attended:
            db.session.delete(a)
        else:
            a.beneficiary_id = keep.id
    for model in (ServiceRecord, FormSubmission, Feedback, ConsentRecord):
        model.query.filter_by(beneficiary_id=dup.id).update({"beneficiary_id": keep.id}, synchronize_session=False)
    for h in Household.query.filter_by(head_id=dup.id):
        h.head_id = keep.id
    if not keep.household_id and dup.household_id:
        keep.household_id = dup.household_id
    dup.status, dup.merged_into_id, dup.household_id = "merged", keep.id, None
    audit.record("beneficiary.merged", f"{dup.code} merged into {keep.code}", entity=keep)
    db.session.commit()
    db.session.expire_all()
    flash(f"{dup.code} was merged into {keep.code}.", "success")
    return redirect(url_for("beneficiaries.detail", bid=keep.id))


@bp.route("/<int:bid>/anonymize", methods=["POST"])
def anonymize(bid):
    """Remove personal details but keep sex, age group and place, so totals stay correct."""
    b = load(bid)
    if not can_manage_beneficiary(b):
        abort(403)
    if not ActionForm().validate_on_submit():
        abort(400)
    if b.status != "exited" and b.consent_state != "withdrawn":
        flash("Only people who have exited or withdrawn consent can be anonymized.", "danger")
        return redirect(url_for("beneficiaries.detail", bid=b.id))
    if b.date_of_birth:
        b.birth_year = b.date_of_birth.year
    b.first_name, b.last_name, b.other_names = "Anonymized", b.code, None
    b.date_of_birth = b.disability_type = b.phone_enc = b.phone_index = None
    b.id_type = b.id_number_enc = b.id_number_index = b.vulnerabilities = b.notes = b.community = None
    b.relationship_to_head, b.household_id = None, None
    for c in b.consents:
        c.guardian_name = None
    for f in Feedback.query.filter_by(beneficiary_id=b.id):
        f.submitter_name, f.contact_enc = None, None
    b.anonymized_at = utcnow()
    b.status = "exited"
    audit.record("beneficiary.anonymized", f"Personal details of {b.code} removed", entity=b)
    db.session.commit()
    flash("Personal details removed. Sex, age group and place are kept for statistics.", "success")
    return redirect(url_for("beneficiaries.detail", bid=b.id))


# --- export ----------------------------------------------------------------------------------

@bp.route("/export.xlsx")
@require_permission("beneficiaries.export")
def export():
    import openpyxl
    from openpyxl.styles import Font
    from app.analytics_export import safe_row
    personal = can("beneficiaries.sensitive") and request.args.get("personal") == "1"
    stmt = visible_beneficiaries_stmt().order_by(Beneficiary.code)
    rows = db.session.execute(stmt).scalars().all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Beneficiaries"
    head = ["Code", "First name", "Surname", "Sex", "Age group", "Disability", "Location", "Community", "Household",
            "Status", "Consent", "Enrolled in", "Registered on"]
    if personal:
        head += ["Date of birth", "Phone", "ID type", "ID number", "Vulnerability"]
    ws.append(head)
    for c in ws[1]:
        c.font = Font(bold=True)
    for b in rows:
        if personal and not can_see_sensitive(b):
            continue
        row = [b.code, b.first_name, b.last_name, SEXES.get(b.sex), b.age_band,
               {True: "Yes", False: "No"}.get(b.disability, ""), b.location.label if b.location else "",
               b.community or "", b.household.code if b.household else "", b.status, b.consent_state,
               ", ".join(e.owner.code for e in b.enrollments), b.registered_on.isoformat()]
        if personal:
            row += [b.date_of_birth.isoformat() if b.date_of_birth else "", decrypt_text(b.phone_enc) or "",
                    b.id_type or "", decrypt_text(b.id_number_enc) or "", ", ".join(b.vulnerabilities or [])]
        ws.append(safe_row(row))
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(10, min(40, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    audit.record("beneficiary.exported", f"Beneficiary list exported ({len(rows)} rows"
                 f"{', with personal details' if personal else ''})")
    db.session.commit()
    return send_file(buf, as_attachment=True, download_name=f"beneficiaries-{date.today()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# --- households ------------------------------------------------------------------------------

@bp.route("/households/")
@require_permission("beneficiaries.view")
def households():
    q = (request.args.get("q") or "").strip()
    visible = visible_beneficiaries_stmt().with_only_columns(Beneficiary.household_id)
    stmt = select(Household).where(Household.organization_id == g.tenant.id)
    from app.rbac import scope_of, ORG
    if scope_of("beneficiaries.view") != ORG:
        stmt = stmt.where(or_(Household.id.in_(visible), Household.created_by_id == current_user.id))
    if q:
        stmt = stmt.where(or_(Household.name.ilike(f"%{q}%"), Household.code.ilike(f"%{q}%"),
                              Household.community.ilike(f"%{q}%")))
    page = db.paginate(stmt.order_by(Household.name), page=page_arg(), per_page=40, error_out=False)
    sizes = dict(db.session.execute(select(Beneficiary.household_id, func.count()).where(
        Beneficiary.household_id.in_([h.id for h in page.items] or [0]), Beneficiary.status != "merged")
        .group_by(Beneficiary.household_id)).all())
    return render_template("beneficiaries/households.html", page=page, q=q, sizes=sizes,
                           form=HouseholdForm(), locations=location_choices(),
                           can_register=can("beneficiaries.register") and not g.get("support_request"))


@bp.route("/households/new", methods=["POST"])
@require_permission("beneficiaries.register")
def household_new():
    if g.get("support_request"):
        abort(403)
    form = HouseholdForm()
    form.location_id.choices = location_choices()
    if form.validate_on_submit():
        if form.location_id.data:
            tenant_get_or_404(Location, form.location_id.data)
        h = Household(organization_id=g.tenant.id, code=next_reference("HH"), name=form.name.data,
                      location_id=form.location_id.data or None, community=form.community.data or None,
                      notes=form.notes.data or None, created_by_id=current_user.id)
        db.session.add(h)
        db.session.flush()
        audit.record("household.created", f"Household {h.code} registered", entity=h)
        db.session.commit()
        flash(f"Household {h.code} added. Choose it when you register or edit its members.", "success")
        return redirect(url_for("beneficiaries.household", hid=h.id))
    flash("Not saved: " + "; ".join(e for es in form.errors.values() for e in es), "danger")
    return redirect(url_for("beneficiaries.households"))


@bp.route("/households/<int:hid>", methods=["GET", "POST"])
@require_permission("beneficiaries.view")
def household(hid):
    h = tenant_get_or_404(Household, hid)
    members = [m for m in h.members if m.status != "merged" and can_see_beneficiary(m)]
    if not members and h.created_by_id != current_user.id and not can_see_any_household():
        abort(404)
    if request.method == "POST":
        if g.get("support_request") or not can("beneficiaries.register"):
            abort(403)
        head = request.form.get("head_id", type=int)
        if ActionForm().validate_on_submit() and head:
            hb = tenant_get_or_404(Beneficiary, head)
            if hb.household_id != h.id or not can_update_beneficiary(hb):
                abort(400)
            h.head_id = hb.id
            hb.relationship_to_head = "Head"
            audit.record("household.head", f"{h.code}: head is {hb.code}", entity=h)
            db.session.commit()
            flash("Household head updated.", "success")
        return redirect(url_for("beneficiaries.household", hid=h.id))
    return render_template("beneficiaries/household.html", h=h, members=members, action_form=ActionForm(),
                           can_edit=can("beneficiaries.register") and not g.get("support_request"))


def can_see_any_household():
    from app.rbac import ORG, scope_of
    return scope_of("beneficiaries.view") == ORG
