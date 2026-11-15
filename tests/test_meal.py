"""Phase 5: MEAL & beneficiaries — register, consent, duplicates, reach, attendance, data collection, feedback."""
import io
from datetime import date, timedelta

import pytest

from app.models import (ActivityAttendance, ActivityReport, Activity, AuditLog, Beneficiary, DataForm, Enrollment,
                        Feedback, FormSubmission, Notification, Programme, Project, ServiceRecord)
from tests.conftest import add_member, login, logout, make_department, make_org, make_staff_profile

YEAR = date.today().year
TODAY = date.today().isoformat()


@pytest.fixture
def env(app, db):
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    dept = make_department(o, "Programmes")
    people = {"org": o, "dept": dept, "admin": admin}
    for key, role in [("pd", "Programme Director"), ("pm", "Project Manager"), ("field", "Field Officer"),
                      ("field2", "Field Officer"), ("po", "Programme Officer"), ("meal", "MEAL Officer"),
                      ("meal2", "MEAL Officer"), ("sg", "Safeguarding Focal Point"), ("ed", "Executive Director"),
                      ("auditor", "Read-only / Auditor"), ("staff", "Staff Member")]:
        u, _ = add_member(o, f"{key}@hope.org", role_name=role)
        people[key] = u
        make_staff_profile(o, u, department=dept if key in ("pd", "pm", "field") else None)
    return people


def W(env, path):
    return f"/o/{env['org'].slug}{path}"


def as_(client, key):
    logout(client)
    login(client, f"{key}@hope.org")


@pytest.fixture
def owners(client, env):
    as_(client, "pd")
    client.post(W(env, "/programmes/new"), data={"title": "Girls Education", "manager_id": env["pd"].id,
                                                  "currency": "GHS", "approved_budget": "0"})
    prog = Programme.query.one()
    client.post(W(env, "/projects/new"), data={"title": "School Water", "manager_id": env["pm"].id,
                                                "currency": "GHS", "approved_budget": "0", "programme_id": prog.id})
    proj = Project.query.one()
    as_(client, "pm")
    client.post(W(env, f"/projects/{proj.id}/team"), data={"user_id": env["field"].id})
    logout(client)
    return prog, proj


def register(client, env, who="meal", first="Amina", last="Issah", sex="female", owner=None, consent_by="self",
             guardian="", confirm=False, **extra):
    data = {"first_name": first, "last_name": last, "sex": sex, "disability": "", "c-given_on": TODAY,
            "c-given_by": consent_by, "c-guardian_name": guardian, "c-purposes": ["services", "followup"],
            "c-method": "written"}
    if owner is not None:
        data["enroll_owner"] = f"{owner.kind}:{owner.id}"
    if confirm:
        data["confirm_new"] = "y"
    data.update(extra)
    as_(client, who)
    return client.post(W(env, "/beneficiaries/new"), data=data, follow_redirects=True)


# --- Register, consent, privacy -----------------------------------------------------------------

def test_register_with_consent_and_encrypted_personal_details(client, env, db, owners):
    prog, proj = owners
    r = register(client, env, owner=proj, age_estimate="24", phone="024 123 4567", id_type="Ghana Card",
                 id_number="GHA-123456789-0", vulnerabilities=["Displaced person"])
    assert b"Registered as BEN/" in r.data
    b = Beneficiary.query.one()
    assert b.code == f"BEN/{YEAR}/0001" and b.birth_year == YEAR - 24 and b.age_band == "18-35"
    assert b.consent_state == "given" and [e.project_id for e in b.enrollments] == [proj.id]
    # stored encrypted, found through the keyed index
    assert "4567" not in (b.phone_enc or "") and "GHA" not in (b.id_number_enc or "")
    assert b.phone_index and b.id_number_index
    seen = AuditLog.query.filter_by(action="beneficiary.viewed_personal").count()
    html = client.get(W(env, f"/beneficiaries/{b.id}")).data.decode()
    assert "024 123 4567" in html and "GHA-123456789-0" in html
    assert AuditLog.query.filter_by(action="beneficiary.viewed_personal").count() == seen + 1
    # a programme officer sees the register but not personal details
    as_(client, "po")
    html = client.get(W(env, f"/beneficiaries/{b.id}")).data.decode()
    assert "Amina" in html and "024 123 4567" not in html and "GHA-123456789-0" not in html


def test_children_need_guardian_consent(client, env, db, owners):
    r = register(client, env, first="Baby", age_estimate="9")
    assert b"must come from a parent" in r.data and Beneficiary.query.count() == 0
    r = register(client, env, first="Baby", age_estimate="9", consent_by="guardian")
    assert b"Give the name" in r.data
    register(client, env, first="Baby", age_estimate="9", consent_by="guardian", guardian="Mariam Issah")
    b = Beneficiary.query.one()
    assert b.is_minor and b.consents[0].guardian_name == "Mariam Issah"


def test_duplicate_detection_and_merge(client, env, db, owners):
    prog, proj = owners
    register(client, env, owner=proj, age_estimate="30", phone="0241112222")
    # same name and birth year → warning, not saved
    r = register(client, env, owner=prog, age_estimate="31")
    assert b"may already be registered" in r.data and Beneficiary.query.count() == 1
    # same phone under another name → warning too
    r = register(client, env, first="Aminatu", last="Mahama", phone="+233 24 111 2222")
    assert b"may already be registered" in r.data and b"BEN/" in r.data
    # confirmed as a different person → saved
    register(client, env, owner=prog, age_estimate="31", confirm=True)
    keep, dup = Beneficiary.query.order_by(Beneficiary.id).all()
    as_(client, "meal")
    client.post(W(env, f"/beneficiaries/{dup.id}/services"), data={
        "s-owner": f"programme:{prog.id}", "s-service_type": "School kit", "s-delivered_on": TODAY})
    # a field officer cannot merge
    as_(client, "field")
    assert client.post(W(env, f"/beneficiaries/{keep.id}/merge"), data={"duplicate_code": dup.code}).status_code == 403
    as_(client, "meal")
    client.post(W(env, f"/beneficiaries/{keep.id}/merge"), data={"duplicate_code": dup.code})
    db.session.expire_all()
    keep, dup = db.session.get(Beneficiary, keep.id), db.session.get(Beneficiary, dup.id)
    assert dup.status == "merged" and dup.merged_into_id == keep.id
    assert {(e.programme_id, e.project_id) for e in keep.enrollments} == {(None, proj.id), (prog.id, None)}
    assert ServiceRecord.query.one().beneficiary_id == keep.id
    from app.meal_logic import reach
    from flask import g
    g.tenant_id = env["org"].id
    assert reach(db.session.get(Programme, prog.id))["total"] == 1  # one person, not two


def test_field_officer_scope(client, env, db, owners):
    prog, proj = owners
    register(client, env, first="Kofi", last="Mensah", sex="male", owner=proj)      # in field's project
    register(client, env, first="Esi", last="Owusu", owner=prog)                   # programme only
    kofi, esi = Beneficiary.query.order_by(Beneficiary.id).all()
    as_(client, "field")
    listing = client.get(W(env, "/beneficiaries/")).data.decode()
    assert "Kofi" in listing and "Esi" not in listing
    assert client.get(W(env, f"/beneficiaries/{esi.id}")).status_code == 404
    # cannot enrol anyone in a programme they are not part of
    assert client.post(W(env, f"/beneficiaries/{kofi.id}/enroll"), data={
        "owner": f"programme:{prog.id}", "enrolled_on": TODAY}).status_code == 403
    # registers someone themself (no enrolment): still visible to them
    register(client, env, who="field", first="Yaw", last="Darko", sex="male")
    yaw = Beneficiary.query.filter_by(first_name="Yaw").one()
    assert client.get(W(env, f"/beneficiaries/{yaw.id}")).status_code == 200
    as_(client, "field2")  # another field officer, not on the project
    assert client.get(W(env, f"/beneficiaries/{kofi.id}")).status_code == 404
    as_(client, "staff")
    assert client.get(W(env, "/beneficiaries/")).status_code == 403


def test_withdrawn_consent_blocks_new_records_and_allows_anonymizing(client, env, db, owners):
    prog, proj = owners
    register(client, env, owner=proj, age_estimate="40", phone="0200000001", id_number="X1",
             vulnerabilities=["Chronic illness"])
    b = Beneficiary.query.one()
    as_(client, "meal")
    r = client.post(W(env, f"/beneficiaries/{b.id}/anonymize"), data={}, follow_redirects=True)
    assert b"Only people who have exited" in r.data
    client.post(W(env, f"/beneficiaries/{b.id}/consent/withdraw"), data={"note": "Moved away"})
    r = client.post(W(env, f"/beneficiaries/{b.id}/services"), data={
        "s-owner": f"project:{proj.id}", "s-service_type": "Kit", "s-delivered_on": TODAY}, follow_redirects=True)
    assert b"Record this person" in r.data and ServiceRecord.query.count() == 0
    client.post(W(env, f"/beneficiaries/{b.id}/anonymize"), data={})
    db.session.expire_all()
    b = db.session.get(Beneficiary, b.id)
    assert b.anonymized_at and b.first_name == "Anonymized" and b.last_name == b.code
    assert b.phone_enc is None and b.id_number_enc is None and b.vulnerabilities is None and b.date_of_birth is None
    assert b.sex == "female" and b.birth_year == YEAR - 40 and b.enrollments  # statistics kept


# --- Reach and attendance -------------------------------------------------------------------------

def test_reach_counts_each_person_once_across_programme_and_projects(client, env, db, owners):
    from app.exporting import report_data
    from app.meal_logic import reach
    prog, proj = owners
    register(client, env, first="A", last="One", owner=proj)
    register(client, env, first="B", last="Two", sex="male", owner=prog)
    a, b2 = Beneficiary.query.order_by(Beneficiary.id).all()
    as_(client, "meal")
    client.post(W(env, f"/beneficiaries/{a.id}/enroll"), data={"owner": f"programme:{prog.id}", "enrolled_on": TODAY})
    # an activity session in the project with named attendance
    as_(client, "pm")
    client.post(W(env, f"/projects/{proj.id}/activities/new"), data={"title": "Hygiene session", "planned_budget": "0"})
    act = Activity.query.one()
    db.session.add(ActivityReport(organization_id=env["org"].id, activity_id=act.id, report_date=date.today(),
                                  participants_female=12, participants_male=8, summary="Held"))
    db.session.commit()
    rep = ActivityReport.query.one()
    url = W(env, f"/projects/{proj.id}/activities/{act.id}/reports/{rep.id}/attendance")
    html = client.get(url).data.decode()
    assert "A One" in html and "B Two" not in html  # only people enrolled in this project
    assert client.post(url, data={"beneficiary_id": [b2.id]}).status_code == 400
    client.post(url, data={"beneficiary_id": [a.id]})
    assert ActivityAttendance.query.count() == 1
    html = client.get(W(env, f"/projects/{proj.id}/activities/{act.id}")).data.decode()
    assert "Named attendance: 1 registered (1 female, 0 male)" in html
    from flask import g
    g.tenant_id = env["org"].id
    db.session.expire_all()
    prog, proj = db.session.get(Programme, prog.id), db.session.get(Project, proj.id)
    assert reach(proj)["total"] == 1
    r = reach(prog)
    assert r["total"] == 2 and r["female"] == 1 and r["male"] == 1  # A counted once despite two enrolments
    assert reach(prog, include_projects=False)["total"] == 2
    assert report_data(prog)["reach"]["total"] == 2
    as_(client, "pd")
    html = client.get(W(env, f"/programmes/{prog.id}/beneficiaries")).data.decode()
    assert "People reached, each counted once" in html


# --- Data collection ------------------------------------------------------------------------------

def _make_form(client, env, proj, link="optional"):
    as_(client, "meal")
    client.post(W(env, "/meal/forms/new"), data={"title": "Household water survey", "owner": f"project:{proj.id}",
                                                   "beneficiary_link": link})
    f = DataForm.query.one()
    for label, ftype, opts, req in [("Main water source", "choice", "Borehole\nRiver\nVendor", True),
                                    ("Litres per day", "number", "", True),
                                    ("Treats water", "yes_no", "", False),
                                    ("Problems", "multi", "Distance\nCost\nQueues", False)]:
        client.post(W(env, f"/meal/forms/{f.id}"), data={"label": label, "field_type": ftype, "options": opts,
                                                          "required": "y" if req else ""})
    return f


def test_data_collection_form_lifecycle(client, env, db, owners):
    prog, proj = owners
    f = _make_form(client, env, proj)
    keys = [q.key for q in f.fields]
    assert keys == ["main_water_source", "litres_per_day", "treats_water", "problems"]
    r = client.post(W(env, f"/meal/forms/{f.id}"), data={"label": "Bad", "field_type": "choice", "options": "Only one"})
    assert b"at least two choices" in r.data
    as_(client, "field")
    assert client.get(W(env, f"/meal/forms/{f.id}/collect")).status_code == 403  # still a draft
    as_(client, "meal")
    client.post(W(env, f"/meal/forms/{f.id}/publish"), data={})
    register(client, env, owner=proj)
    ben = Beneficiary.query.one()
    as_(client, "field")
    url = W(env, f"/meal/forms/{f.id}/collect")
    r = client.post(url, data={"collected_on": TODAY, "q_main_water_source": "Lake", "q_litres_per_day": "abc"})
    assert b"Choose from the list" in r.data and b"Enter a number" in r.data and FormSubmission.query.count() == 0
    client.post(url, data={"collected_on": TODAY, "beneficiary_code": ben.code, "q_main_water_source": "Borehole",
                           "q_litres_per_day": "40", "q_treats_water": "yes", "q_problems": ["Distance", "Queues"]})
    client.post(url, data={"collected_on": TODAY, "q_main_water_source": "River", "q_litres_per_day": "20"})
    s1, s2 = FormSubmission.query.order_by(FormSubmission.id).all()
    assert s1.beneficiary_id == ben.id and s1.answers["problems"] == ["Distance", "Queues"]
    assert s1.answers["litres_per_day"] == 40.0
    # the collector cannot check their own answers; questions are locked once answers exist
    as_(client, "meal")
    client.post(W(env, f"/meal/forms/{f.id}/close"), data={})
    r = client.post(W(env, f"/meal/forms/{f.id}/draft"), data={}, follow_redirects=True)
    assert b"can no longer change" in r.data
    client.post(W(env, f"/meal/forms/{f.id}/reopen"), data={})
    client.post(W(env, f"/meal/forms/{f.id}/answers/{s1.id}/verify"), data={})
    r = client.post(W(env, f"/meal/forms/{f.id}/answers/{s2.id}/reject"), data={}, follow_redirects=True)
    assert b"Say why" in r.data
    db.session.expire_all()
    assert db.session.get(FormSubmission, s1.id).status == "verified"
    html = client.get(W(env, f"/meal/forms/{f.id}/answers")).data.decode()
    assert "Average" in html and "30" in html  # (40 + 20) / 2
    x = client.get(W(env, f"/meal/forms/{f.id}/answers.xlsx"))
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(x.data)).active
    assert ws.max_row == 3 and ws.cell(1, 7).value == "Main water source"
    # someone outside the project cannot see the form
    as_(client, "field2")
    assert client.get(W(env, f"/meal/forms/{f.id}")).status_code == 404


def test_form_beneficiary_must_consent_and_be_enrolled(client, env, db, owners):
    prog, proj = owners
    f = _make_form(client, env, proj, link="required")
    client.post(W(env, f"/meal/forms/{f.id}/publish"), data={})
    register(client, env, first="Not", last="Enrolled", owner=prog)
    other = Beneficiary.query.one()
    as_(client, "meal")
    base = {"collected_on": TODAY, "q_main_water_source": "Borehole", "q_litres_per_day": "5"}
    r = client.post(W(env, f"/meal/forms/{f.id}/collect"), data=base)
    assert b"Enter the beneficiary" in r.data
    r = client.post(W(env, f"/meal/forms/{f.id}/collect"), data=base | {"beneficiary_code": other.code})
    assert b"not enrolled in" in r.data and FormSubmission.query.count() == 0


# --- Feedback & complaints ------------------------------------------------------------------------

def _feedback(client, env, who="field", **over):
    data = {"received_on": TODAY, "channel": "community_meeting", "category": "complaint", "priority": "normal",
            "summary": "Borehole broken in Kumbungu", "description": "The borehole has not worked for a week.",
            "submitter_name": "Alhassan", "contact": "0209998888", "wants_response": "y"}
    data.update(over)
    as_(client, who)
    r = client.post(W(env, "/feedback/new"), data=data, follow_redirects=True)
    assert r.status_code == 200
    return Feedback.query.order_by(Feedback.id.desc()).first()


def test_feedback_lifecycle(client, env, db, owners):
    prog, proj = owners
    f = _feedback(client, env, owner=f"project:{proj.id}")
    assert f.code == f"FB/{YEAR}/0001" and not f.sensitive and f.due_date == date.today() + timedelta(days=7)
    assert "0209998888" not in (f.contact_enc or "")
    # feedback managers and the project manager are told
    for key in ("meal", "pm"):
        assert Notification.query.filter_by(user_id=env[key].id, kind="feedback").count() == 1, key
    as_(client, "meal")
    client.post(W(env, f"/feedback/{f.id}/acknowledge"), data={})
    client.post(W(env, f"/feedback/{f.id}/assign"), data={"assigned_to_id": env["field"].id})
    r = client.post(W(env, f"/feedback/{f.id}/close"), data={"satisfaction": "satisfied"}, follow_redirects=True)
    assert b"Record the response" in r.data
    as_(client, "field")  # the assignee handles it
    client.post(W(env, f"/feedback/{f.id}/respond"), data={"response": "Repaired on Friday.", "responded_on": TODAY})
    client.post(W(env, f"/feedback/{f.id}/close"), data={"satisfaction": "satisfied"})
    db.session.expire_all()
    f = db.session.get(Feedback, f.id)
    assert f.status == "closed" and f.satisfaction == "satisfied" and f.responded_on == date.today()
    assert [a.action for a in f.actions] == ["received", "acknowledged", "assigned", "responded", "closed"]
    as_(client, "meal")
    html = client.get(W(env, "/meal/")).data.decode()
    assert "Satisfied with the outcome" in html and "100%" in html


def test_sensitive_feedback_is_confidential(client, env, db, owners):
    f = _feedback(client, env, category="safeguarding", summary="Report about a volunteer",
                  description="Details of the concern.")
    assert f.sensitive and f.priority == "high" and f.due_date == date.today() + timedelta(days=3)
    assert Notification.query.filter_by(user_id=env["sg"].id, kind="feedback").count() == 1
    assert Notification.query.filter_by(user_id=env["meal"].id, kind="feedback").count() == 0
    assert "volunteer" not in (Notification.query.filter_by(user_id=env["sg"].id).one().body or "")
    for key in ("meal", "ed", "pd", "auditor"):
        as_(client, key)
        assert client.get(W(env, f"/feedback/{f.id}")).status_code == 404, key
        assert "Report about a volunteer" not in client.get(W(env, "/feedback/?status=any")).data.decode()
    as_(client, "ed")
    assert "Sensitive cases open" in client.get(W(env, "/meal/")).data.decode()
    seen = AuditLog.query.filter_by(action="feedback.viewed_sensitive").count()  # the recorder's own view
    as_(client, "sg")
    assert b"Report about a volunteer" in client.get(W(env, f"/feedback/{f.id}")).data
    assert AuditLog.query.filter_by(action="feedback.viewed_sensitive").count() == seen + 1
    # it can only be assigned to safeguarding staff
    assert client.post(W(env, f"/feedback/{f.id}/assign"), data={"assigned_to_id": env["meal"].id},
                       follow_redirects=True).status_code == 200
    db.session.expire_all()
    assert db.session.get(Feedback, f.id).assigned_to_id is None
    # the staff member who took the report can still follow it
    as_(client, "field")
    assert client.get(W(env, f"/feedback/{f.id}")).status_code == 200


def test_public_feedback_page(client, app, env, db):
    url = f"/f/{env['org'].slug}"
    logout(client)
    assert client.get(url).status_code == 404  # off by default
    as_(client, "field")
    assert client.get(W(env, "/feedback/settings")).status_code == 403
    as_(client, "meal")
    client.post(W(env, "/feedback/settings"), data={"accept_public_feedback": "y",
                                                     "public_feedback_intro": "We read every message."})
    logout(client)
    html = client.get(url).data.decode()
    assert "We read every message." in html
    r = client.post(url, data={"category": "fraud", "message": "Someone is selling the food rations.",
                               "anonymous": "y", "name": "Should not be kept", "contact": "0201"})
    assert b"Your reference is" in r.data
    f = Feedback.query.one()
    assert f.source == "public" and f.sensitive and f.anonymous and f.submitter_name is None and f.contact_enc is None
    assert Notification.query.filter_by(user_id=env["sg"].id, kind="feedback").count() == 1
    # bots filling the hidden field are ignored
    client.post(url, data={"category": "question", "message": "Buy cheap watches now", "website": "spam.example"})
    assert Feedback.query.count() == 1


def test_feedback_reminders(client, app, env, db, owners):
    f = _feedback(client, env, priority="urgent")
    f.due_date = date.today() - timedelta(days=1)
    db.session.commit()
    runner = app.test_cli_runner()
    runner.invoke(args=["oims", "send-reminders"])
    runner.invoke(args=["oims", "send-reminders"])
    assert Notification.query.filter_by(user_id=env["meal"].id, kind="reminder").count() == 1


# --- Isolation, support, export, pages ------------------------------------------------------------

def test_meal_tenant_isolation(client, app, env, db, owners):
    prog, proj = owners
    register(client, env, phone="0244445555")
    b = Beneficiary.query.one()
    f = _feedback(client, env)
    o2, _ = make_org("Rival Org", admin_email="admin@rival.org")
    other = app.test_client()
    login(other, "admin@rival.org")
    assert other.get(f"/o/{o2.slug}/beneficiaries/{b.id}").status_code == 404
    assert other.get(f"/o/{o2.slug}/feedback/{f.id}").status_code == 404
    assert b"Amina" not in other.get(f"/o/{o2.slug}/beneficiaries/").data
    # the same phone in another organization is not a "duplicate" there
    r = other.post(f"/o/{o2.slug}/beneficiaries/new", data={
        "first_name": "Amina", "last_name": "Issah", "sex": "female", "phone": "0244445555", "c-given_on": TODAY,
        "c-given_by": "self", "c-purposes": ["services"], "c-method": "written"}, follow_redirects=True)
    assert b"Registered as" in r.data


def test_support_access_is_read_only_and_hides_personal_details(client, env, db, owners):
    from app.models import PlatformRole, SupportAccessRequest, User, utcnow
    from tests.conftest import make_staff
    register(client, env, phone="0249990000")
    b = Beneficiary.query.one()
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    req = SupportAccessRequest(organization_id=env["org"].id, reason="Checking a beneficiary problem",
                               requested_by_id=User.query.filter_by(email="support@holido.org").one().id,
                               duration_minutes=30, status="approved", starts_at=utcnow(),
                               expires_at=utcnow() + timedelta(minutes=30))
    db.session.add(req)
    db.session.commit()
    logout(client)
    login(client, "support@holido.org")
    client.post(f"/platform/support/{req.id}/enter")
    html = client.get(W(env, f"/beneficiaries/{b.id}")).data.decode()
    assert "Amina" in html and "0249990000" not in html
    assert client.post(W(env, f"/beneficiaries/{b.id}/consent/withdraw"), data={}).status_code == 403
    assert client.get(W(env, "/beneficiaries/new")).status_code == 403


def test_export_permissions(client, env, db, owners):
    import openpyxl
    register(client, env, phone="0241231234")
    as_(client, "field")
    assert client.get(W(env, "/beneficiaries/export.xlsx")).status_code == 403
    as_(client, "pd")  # may export, but not personal details
    ws = openpyxl.load_workbook(io.BytesIO(client.get(W(env, "/beneficiaries/export.xlsx?personal=1")).data)).active
    assert "Phone" not in [c.value for c in ws[1]] and ws.max_row == 2
    as_(client, "meal")
    ws = openpyxl.load_workbook(io.BytesIO(client.get(W(env, "/beneficiaries/export.xlsx?personal=1")).data)).active
    assert "Phone" in [c.value for c in ws[1]] and "0241231234" in [c.value for c in ws[2]]
    assert AuditLog.query.filter_by(action="beneficiary.exported").count() == 2


def test_all_meal_pages_render(client, env, db, owners):
    prog, proj = owners
    register(client, env, owner=proj)
    b = Beneficiary.query.one()
    f = _make_form(client, env, proj)
    fb = _feedback(client, env, who="meal")
    as_(client, "meal")
    client.post(W(env, "/beneficiaries/households/new"), data={"name": "Issah household"})
    from app.models import Household
    h = Household.query.one()
    pages = ["/meal/", "/beneficiaries/", "/beneficiaries/new", f"/beneficiaries/{b.id}", f"/beneficiaries/{b.id}/edit",
             "/beneficiaries/households/", f"/beneficiaries/households/{h.id}", "/meal/forms/", "/meal/forms/new",
             f"/meal/forms/{f.id}", f"/meal/forms/{f.id}/edit", f"/meal/forms/{f.id}/answers", "/feedback/",
             "/feedback/new", f"/feedback/{fb.id}", "/feedback/settings", f"/programmes/{prog.id}/beneficiaries",
             f"/projects/{proj.id}/beneficiaries", f"/beneficiaries/?owner=project:{proj.id}&sex=female&age=Unknown"]
    for p in pages:
        assert client.get(W(env, p)).status_code == 200, p
    client.post(W(env, f"/meal/forms/{f.id}/publish"), data={})
    assert client.get(W(env, f"/meal/forms/{f.id}/collect")).status_code == 200
    for key in ("auditor", "ed", "field", "sg"):
        as_(client, key)
        assert client.get(W(env, "/meal/")).status_code == 200, key
    as_(client, "auditor")
    assert client.get(W(env, f"/beneficiaries/{b.id}")).status_code == 200
    assert client.get(W(env, "/beneficiaries/new")).status_code == 403
    assert client.post(W(env, "/feedback/new"), data={}).status_code == 403
