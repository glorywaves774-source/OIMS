"""Phase 2: departments, staff & HR, leave, attendance, tasks, meetings, correspondence, communication."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import (AttendanceRecord, Correspondence, Department, LeaveRequest, LeaveType, Meeting, Membership,
                        Notification, StaffProfile, StaffTransfer, Task, User, utcnow)
from tests.conftest import (add_member, login, logout, make_department, make_org, make_staff, make_staff_profile)


@pytest.fixture
def org(app):
    """An organization with two departments and people in different roles."""
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    prog = make_department(o, "Programmes")
    fin = make_department(o, "Finance")
    people = {"admin": admin}
    for key, email, role, dept in [
        ("hr", "hr@hope.org", "HR Officer", None),
        ("head", "head@hope.org", "Department Head", prog),
        ("ama", "ama@hope.org", "Staff Member", prog),
        ("kofi", "kofi@hope.org", "Staff Member", fin),
        ("records", "records@hope.org", "Records Officer", None),
        ("ed", "ed@hope.org", "Executive Director", None),
    ]:
        user, _ = add_member(o, email, role_name=role)
        user.full_name = key.capitalize() + " Person"
        people[key] = user
        people[key + "_staff"] = make_staff_profile(o, user, department=dept)
    return {"org": o, "prog": prog, "fin": fin, **people}


def url(o, path):
    return f"/o/{o.slug}{path}"


# --- Departments -------------------------------------------------------------------------

def test_department_management(client, org):
    o = org["org"]
    login(client, "hr@hope.org")
    r = client.post(url(o, "/departments/new"), data={"name": "Logistics", "code": "LOG",
                                                      "head_staff_id": org["head_staff"].id})
    assert r.status_code == 302
    d = Department.query.filter_by(name="Logistics").one()
    assert d.head_staff_id == org["head_staff"].id
    r = client.post(url(o, "/departments/new"), data={"name": "Logistics"})
    assert b"already has this name" in r.data
    assert client.get(url(o, f"/departments/{d.id}")).status_code == 200
    logout(client)
    login(client, "ama@hope.org")
    assert client.get(url(o, "/departments/")).status_code == 200
    assert client.get(url(o, "/departments/new")).status_code == 403


# --- Staff & HR records -------------------------------------------------------------------

def test_register_staff_and_transfer(client, org, db):
    o = org["org"]
    login(client, "hr@hope.org")
    data = {"full_name": "Yaw Driver", "employee_number": "DRV-01", "department_id": org["prog"].id,
            "status": "active", "employment_type": "Permanent", "emergency_phone": "0244000000"}
    assert client.post(url(o, "/staff/new"), data=data).status_code == 302
    s = StaffProfile.query.filter_by(employee_number="DRV-01").one()
    dup = client.post(url(o, "/staff/new"), data=dict(data, full_name="Other"))
    assert b"already has this number" in dup.data
    client.post(url(o, f"/staff/{s.id}/edit"), data=dict(data, department_id=org["fin"].id))
    t = StaffTransfer.query.filter_by(staff_id=s.id).one()
    assert t.from_department_id == org["prog"].id and t.to_department_id == org["fin"].id
    client.post(url(o, f"/staff/{s.id}/training"), data={"title": "First aid", "provider": "Red Cross"})
    client.post(url(o, f"/staff/{s.id}/review"), data={"period": "H1 2026", "rating": "4", "summary": "Good"})
    html = client.get(url(o, f"/staff/{s.id}")).data.decode()
    assert "First aid" in html and "H1 2026" in html and "0244000000" in html


def test_hr_records_visibility(client, org):
    o = org["org"]
    kofi = org["kofi_staff"]
    from app.extensions import db
    kofi.emergency_phone = "0200111222"
    ama = org["ama_staff"]
    ama.emergency_phone = "0200999888"
    db.session.commit()
    # A staff member sees the directory entry of a colleague but not their HR record...
    login(client, "ama@hope.org")
    assert client.get(url(o, "/staff/")).status_code == 200
    other = client.get(url(o, f"/staff/{kofi.id}")).data.decode()
    assert "0200111222" not in other and "Performance reviews" not in other
    # ...and does see their own.
    assert "0200999888" in client.get(url(o, f"/staff/{ama.id}")).data.decode()
    logout(client)
    # A department head sees records for their own department only.
    login(client, "head@hope.org")
    assert "0200999888" in client.get(url(o, f"/staff/{ama.id}")).data.decode()
    assert "0200111222" not in client.get(url(o, f"/staff/{kofi.id}")).data.decode()
    assert client.post(url(o, f"/staff/{kofi.id}/training"), data={"title": "x"}).status_code == 403


def test_staff_exit(client, org, db):
    o = org["org"]
    login(client, "hr@hope.org")
    k = org["kofi_staff"]
    r = client.post(url(o, f"/staff/{k.id}/exit"), data={"exit_date": "2026-11-30", "exit_type": "Resignation",
                                                          "remove_access": "y"})
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.get(StaffProfile, k.id).status == "exited"
    assert Membership.query.filter_by(organization_id=o.id, user_id=org["kofi"].id).one().status == "suspended"
    assert client.get(url(o, f"/staff/{k.id}/edit")).status_code == 302  # read-only now


# --- Leave ------------------------------------------------------------------------------------

def _next_monday():
    d = date.today() + timedelta(days=7)
    return d - timedelta(days=d.weekday())


def test_leave_request_and_approval(client, app, org, db):
    o = org["org"]
    annual = LeaveType.query.filter_by(organization_id=o.id, name="Annual leave").one()
    mon = _next_monday()
    login(client, "ama@hope.org")
    r = client.post(url(o, "/leave/request"), data={"leave_type_id": annual.id, "start_date": mon.isoformat(),
                                                    "end_date": (mon + timedelta(days=6)).isoformat()})
    assert r.status_code == 302
    req = LeaveRequest.query.one()
    assert req.days == 5  # Mon–Sun counts working days only
    # head of Programmes was notified
    assert Notification.query.filter_by(user_id=org["head"].id, kind="leave").count() == 1
    # overlapping request rejected; entitlement exceeded rejected
    r = client.post(url(o, "/leave/request"), data={"leave_type_id": annual.id, "start_date": mon.isoformat(),
                                                    "end_date": mon.isoformat()})
    assert b"already have leave" in r.data
    later = mon + timedelta(days=28)
    r = client.post(url(o, "/leave/request"), data={"leave_type_id": annual.id, "start_date": later.isoformat(),
                                                    "end_date": (later + timedelta(days=20)).isoformat()})
    assert b"exceed your 15 days" in r.data
    # cannot approve own leave even with the permission? (staff member has none)
    assert client.post(url(o, f"/leave/{req.id}/approve"), data={}).status_code == 403
    logout(client)

    # Head of a different department cannot approve; head of Programmes can
    other = app.test_client()
    head_fin, _ = add_member(o, "headfin@hope.org", role_name="Department Head")
    from tests.conftest import make_staff_profile as msp
    msp(o, head_fin, department=org["fin"])
    login(other, "headfin@hope.org")
    assert other.post(url(o, f"/leave/{req.id}/approve"), data={}).status_code == 403
    login(client, "head@hope.org")
    client.post(url(o, f"/leave/{req.id}/approve"), data={"note": "Enjoy"})
    db.session.expire_all()
    assert db.session.get(LeaveRequest, req.id).status == "approved"
    assert Notification.query.filter_by(user_id=org["ama"].id, kind="leave").count() == 1
    logout(client)
    login(client, "ama@hope.org")
    html = client.get(url(o, "/leave/")).data.decode()
    assert "10 of 15 days left" in html
    client.post(url(o, f"/leave/{req.id}/cancel"), data={})
    db.session.expire_all()
    assert db.session.get(LeaveRequest, req.id).status == "cancelled"


def test_attendance_register_scope(client, org, db):
    o = org["org"]
    login(client, "head@hope.org")
    html = client.get(url(o, "/attendance/")).data.decode()
    assert "Ama Person" in html and "Kofi Person" not in html
    today = date.today().isoformat()
    data = {"date": today, f"status_{org['ama_staff'].id}": "present", f"status_{org['kofi_staff'].id}": "absent"}
    client.post(url(o, "/attendance/"), data=data)
    recs = AttendanceRecord.query.all()
    assert [(r.staff_id, r.status) for r in recs] == [(org["ama_staff"].id, "present")]
    logout(client)
    login(client, "ama@hope.org")
    assert client.get(url(o, "/attendance/")).status_code == 403


# --- Tasks ---------------------------------------------------------------------------------------

def test_task_flow_and_visibility(client, app, org, db):
    o = org["org"]
    login(client, "head@hope.org")
    r = client.post(url(o, "/tasks/new"), data={"title": "Prepare field report", "assigned_to_id": org["ama"].id,
                                                "priority": "high", "due_date": "2026-12-01",
                                                "department_id": org["prog"].id})
    assert r.status_code == 302
    t = Task.query.one()
    assert Notification.query.filter_by(user_id=org["ama"].id, kind="task").count() == 1
    logout(client)
    login(client, "ama@hope.org")
    assert client.get(url(o, f"/tasks/{t.id}")).status_code == 200
    client.post(url(o, f"/tasks/{t.id}/status"), data={"status": "done"})
    client.post(url(o, f"/tasks/{t.id}/comment"), data={"body": "Submitted to the head"})
    db.session.expire_all()
    t = db.session.get(Task, t.id)
    assert t.status == "done" and t.completed_at is not None and len(t.comments) == 1
    logout(client)
    login(client, "kofi@hope.org")  # other department, staff member
    assert client.get(url(o, f"/tasks/{t.id}")).status_code == 404
    assert client.post(url(o, f"/tasks/{t.id}/status"), data={"status": "todo"}).status_code == 403
    assert b"Prepare field report" not in client.get(url(o, "/tasks/?view=all&status=any")).data
    logout(client)
    login(client, "ed@hope.org")  # organization-wide view
    assert b"Prepare field report" in client.get(url(o, "/tasks/?view=all&status=any")).data


def test_task_assignee_must_be_member(client, org):
    o = org["org"]
    outsider = make_staff("outsider@elsewhere.org", role=None)
    login(client, "head@hope.org")
    r = client.post(url(o, "/tasks/new"), data={"title": "X", "assigned_to_id": outsider.id, "priority": "normal"})
    assert r.status_code in (200, 400) and Task.query.count() == 0


# --- Meetings -----------------------------------------------------------------------------------------

def test_meeting_lifecycle(client, org, db):
    o = org["org"]
    o.timezone = "Africa/Nairobi"  # UTC+3, to check conversion
    db.session.commit()
    login(client, "head@hope.org")
    r = client.post(url(o, "/meetings/new"), data={
        "title": "Programme review", "starts_at": "2026-12-03T10:00", "ends_at": "2026-12-03T11:30",
        "location": "Board room", "department_id": org["prog"].id, "participants": [org["ama"].id],
        "agenda": "1. Progress\n2. AOB"})
    assert r.status_code == 302
    m = Meeting.query.one()
    assert m.starts_at.replace(tzinfo=timezone.utc) == datetime(2026, 12, 3, 7, 0, tzinfo=timezone.utc)
    assert {p.user_id for p in m.participants} == {org["head"].id, org["ama"].id}
    assert Notification.query.filter_by(user_id=org["ama"].id, kind="meeting").count() == 1
    html = client.get(url(o, f"/meetings/{m.id}")).data.decode()
    assert "10:00" in html  # shown in local time
    client.post(url(o, f"/meetings/{m.id}/minutes"), data={"minutes": "Discussed progress."})
    client.post(url(o, f"/meetings/{m.id}/decision"), data={"text": "Extend the project by one month"})
    client.post(url(o, f"/meetings/{m.id}/action"), data={"title": "Draft extension letter",
                                                           "assigned_to_id": org["ama"].id, "due_date": "2026-12-10"})
    client.post(url(o, f"/meetings/{m.id}/attendance"), data={"present": [org["ama"].id, org["head"].id]})
    task = Task.query.filter_by(meeting_id=m.id).one()
    assert task.assigned_to_id == org["ama"].id
    rep = client.get(url(o, f"/meetings/{m.id}/report")).data.decode()
    assert "Extend the project" in rep and "Draft extension letter" in rep
    logout(client)
    login(client, "ama@hope.org")
    assert client.get(url(o, f"/meetings/{m.id}")).status_code == 200
    client.post(url(o, f"/meetings/{m.id}/rsvp/declined"))
    assert client.post(url(o, f"/meetings/{m.id}/minutes"), data={"minutes": "hack"}).status_code == 403
    assert client.get(url(o, f"/tasks/{task.id}")).status_code == 200
    logout(client)
    login(client, "kofi@hope.org")
    assert client.get(url(o, f"/meetings/{m.id}")).status_code == 404


# --- Correspondence ------------------------------------------------------------------------------------

def test_correspondence_register_route_approve(client, app, org, db):
    o = org["org"]
    year = date.today().year
    login(client, "records@hope.org")
    base = {"kind": "incoming", "subject": "Grant agreement", "party": "Ministry of Health", "priority": "high",
            "assigned_to_id": org["head"].id, "department_id": org["prog"].id, "response_due": "2026-12-05"}
    client.post(url(o, "/correspondence/new"), data=base)
    client.post(url(o, "/correspondence/new"), data=dict(base, subject="Second letter", assigned_to_id=0))
    refs = sorted(c.reference_no for c in Correspondence.query.all())
    assert refs == [f"IN/{year}/0001", f"IN/{year}/0002"]
    c = Correspondence.query.filter_by(subject="Grant agreement").one()
    assert c.status == "assigned"
    assert Notification.query.filter_by(user_id=org["head"].id, kind="correspondence").count() == 1
    logout(client)

    # Another organization starts its own numbering
    o2, _ = make_org("Other Org", admin_email="admin@other.org")
    c2 = app.test_client()
    login(c2, "admin@other.org")
    c2.post(f"/o/{o2.slug}/correspondence/new", data=dict(base, assigned_to_id=0, department_id=0))
    assert Correspondence.query.filter_by(organization_id=o2.id).one().reference_no == f"IN/{year}/0001"
    assert c2.get(url(o, f"/correspondence/{c.id}")).status_code == 404

    # Assignee works on it and submits for approval; a staff member cannot see it
    login(client, "head@hope.org")
    client.post(url(o, f"/correspondence/{c.id}/do/start"), data={})
    client.post(url(o, f"/correspondence/{c.id}/do/submit"), data={"note": "Draft reply attached"})
    db.session.expire_all()
    assert db.session.get(Correspondence, c.id).status == "awaiting_approval"
    assert Notification.query.filter_by(user_id=org["ed"].id, kind="correspondence").count() >= 1
    # forward to Ama
    client.post(url(o, f"/correspondence/{c.id}/route"), data={"to_user_id": org["ama"].id, "note": "Please file"})
    logout(client)
    login(client, "kofi@hope.org")
    assert client.get(url(o, f"/correspondence/{c.id}")).status_code == 404
    logout(client)
    login(client, "ed@hope.org")
    client.post(url(o, f"/correspondence/{c.id}/do/approve"), data={})
    db.session.expire_all()
    assert db.session.get(Correspondence, c.id).status == "approved"
    actions = [a.action for a in db.session.get(Correspondence, c.id).actions]
    assert actions[:2] == ["registered", "assigned"] and "forwarded" in actions and "approve" in actions


def test_confidential_correspondence(client, org, db):
    o = org["org"]
    login(client, "records@hope.org")
    client.post(url(o, "/correspondence/new"), data={"kind": "incoming", "subject": "Disciplinary matter",
                                                     "priority": "normal", "confidential": "y",
                                                     "assigned_to_id": org["hr"].id, "department_id": org["prog"].id})
    c = Correspondence.query.one()
    logout(client)
    login(client, "head@hope.org")  # has correspondence.view for the department, but it is confidential
    assert client.get(url(o, f"/correspondence/{c.id}")).status_code == 404
    assert b"Disciplinary" not in client.get(url(o, "/correspondence/")).data
    logout(client)
    login(client, "hr@hope.org")  # the assignee
    assert client.get(url(o, f"/correspondence/{c.id}")).status_code == 200


# --- Announcements, messages, notifications, calendar ------------------------------------------------------

def test_department_announcement(client, org):
    o = org["org"]
    login(client, "hr@hope.org")
    client.post(url(o, "/announcements/new"), data={"title": "Finance retreat", "body": "Friday at 9",
                                                    "department_id": org["fin"].id})
    assert Notification.query.filter_by(user_id=org["kofi"].id, kind="announcement").count() == 1
    assert Notification.query.filter_by(user_id=org["ama"].id, kind="announcement").count() == 0
    logout(client)
    login(client, "ama@hope.org")
    assert b"Finance retreat" not in client.get(url(o, "/announcements")).data
    logout(client)
    login(client, "kofi@hope.org")
    assert b"Finance retreat" in client.get(url(o, "/announcements")).data


def test_messages_are_private(client, app, org):
    o = org["org"]
    login(client, "ama@hope.org")
    r = client.post(url(o, "/messages/new"), data={"recipients": [org["kofi"].id], "subject": "Lunch",
                                                   "body": "Shall we meet at 1?"})
    assert r.status_code == 302
    conv_url = r.headers["Location"]
    logout(client)
    login(client, "kofi@hope.org")
    assert b"Shall we meet at 1?" in client.get(conv_url).data
    client.post(conv_url, data={"body": "Yes, see you"})
    logout(client)
    login(client, "hr@hope.org")
    assert client.get(conv_url).status_code == 404
    # Recipients must belong to the organization
    outsider = make_staff("x@elsewhere.org", role=None)
    r = client.post(url(o, "/messages/new"), data={"recipients": [outsider.id], "body": "hi"})
    assert r.status_code in (200, 400)


def test_notifications_open_and_read_all(client, org, db):
    o = org["org"]
    login(client, "head@hope.org")
    client.post(url(o, "/tasks/new"), data={"title": "T1", "assigned_to_id": org["ama"].id, "priority": "normal"})
    logout(client)
    login(client, "ama@hope.org")
    n = Notification.query.filter_by(user_id=org["ama"].id).one()
    html = client.get(url(o, "/")).data.decode()
    assert "T1" in html  # dashboard shows unread notification and task
    r = client.get(url(o, f"/notifications/{n.id}"))
    assert r.status_code == 302 and "/tasks/" in r.headers["Location"]
    db.session.expire_all()
    assert db.session.get(Notification, n.id).read_at is not None
    logout(client)
    login(client, "kofi@hope.org")
    assert client.get(url(o, f"/notifications/{n.id}")).status_code == 404


def test_calendar_shows_events(client, org):
    o = org["org"]
    login(client, "head@hope.org")
    due = date.today() + timedelta(days=2)
    client.post(url(o, "/tasks/new"), data={"title": "Calendar task", "priority": "normal", "due_date": due.isoformat()})
    html = client.get(url(o, f"/calendar?month={due:%Y-%m}")).data.decode()
    assert "Due: Calendar task" in html
    assert client.get(url(o, "/calendar?scope=organization")).status_code == 200


def test_reminders_are_sent_once(app, org, db):
    o = org["org"]
    t = Task(organization_id=o.id, title="Due soon", assigned_to_id=org["ama"].id, created_by_id=org["head"].id,
             due_date=date.today() + timedelta(days=1))
    db.session.add(t)
    db.session.commit()
    runner = app.test_cli_runner()
    assert runner.invoke(args=["oims", "send-reminders"]).exit_code == 0
    assert runner.invoke(args=["oims", "send-reminders"]).exit_code == 0
    assert Notification.query.filter_by(user_id=org["ama"].id, kind="reminder").count() == 1


# --- Isolation and support access on the new modules ---------------------------------------------------------

def test_new_modules_are_tenant_isolated(client, app, org, db):
    o = org["org"]
    t = Task(organization_id=o.id, title="Secret", assigned_to_id=org["ama"].id, created_by_id=org["ama"].id)
    m = Meeting(organization_id=o.id, title="Private", starts_at=utcnow(), organizer_id=org["admin"].id)
    db.session.add_all([t, m])
    db.session.commit()
    o2, _ = make_org("Rival", admin_email="admin@rival.org")
    login(client, "admin@rival.org")
    for path in (f"/tasks/{t.id}", f"/meetings/{m.id}", f"/staff/{org['ama_staff'].id}",
                 f"/departments/{org['prog'].id}"):
        assert client.get(f"/o/{o2.slug}{path}").status_code == 404, path
    assert client.get(url(o, "/tasks/")).status_code == 404


def test_support_access_is_read_only_on_new_modules(client, org, db):
    from app.models import PlatformRole, SupportAccessRequest
    o = org["org"]
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    req = SupportAccessRequest(organization_id=o.id, requested_by_id=User.query.filter_by(email="support@holido.org").one().id,
                               reason="Checking tasks", duration_minutes=30, status="approved",
                               starts_at=utcnow(), expires_at=utcnow() + timedelta(minutes=30))
    db.session.add(req)
    db.session.commit()
    login(client, "support@holido.org")
    client.post(f"/platform/support/{req.id}/enter")
    assert client.get(url(o, "/tasks/?view=all")).status_code == 200
    assert client.get(url(o, "/staff/")).status_code == 200
    assert client.post(url(o, "/tasks/new"), data={"title": "x"}).status_code == 403
    assert client.get(url(o, "/messages")).status_code == 403  # private messages are not visible to support
    assert client.get(url(o, f"/staff/{org['ama_staff'].id}")).status_code == 200
    assert b"Performance reviews" not in client.get(url(o, f"/staff/{org['ama_staff'].id}")).data


def test_all_new_pages_render(client, org):
    o = org["org"]
    login(client, "admin@hope.org")
    for path in ("/", "/departments/", "/departments/new", f"/departments/{org['prog'].id}", "/staff/", "/staff/new",
                 f"/staff/{org['ama_staff'].id}", "/leave/", "/leave/types", "/attendance/", "/documents/",
                 "/documents/upload", "/documents/organize", "/correspondence/", "/correspondence/new?kind=memo",
                 "/meetings/", "/meetings/?when=past", "/meetings/new", "/tasks/", "/tasks/new", "/notifications",
                 "/announcements", "/announcements/new", "/messages", "/messages/new", "/calendar",
                 "/calendar?scope=department"):
        assert client.get(url(o, path)).status_code == 200, path
