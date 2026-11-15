"""Phase 4: project management — projects, work breakdown, deliverables, risks, issues, closure, roll-up."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import (Activity, BudgetCategory, BudgetLine, Component, Deliverable, Expenditure, Indicator,
                        IndicatorResult, Issue, Notification, Programme, Project, ProjectClosure, RiskItem, Task)
from tests.conftest import add_member, login, logout, make_department, make_org, make_staff_profile

YEAR = date.today().year
TODAY = date.today().isoformat()


@pytest.fixture
def env(app, db):
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    dept = make_department(o, "Programmes")
    people = {"org": o, "dept": dept, "admin": admin}
    for key, role, d in [("pd", "Programme Director", dept), ("pm", "Project Manager", dept),
                         ("pm2", "Project Manager", None), ("pof", "Project Officer", dept),
                         ("pof2", "Project Officer", None), ("field", "Field Officer", None),
                         ("meal", "MEAL Officer", None), ("fin", "Finance Officer", None),
                         ("fin2", "Finance Officer", None), ("ed", "Executive Director", None),
                         ("staff", "Staff Member", dept), ("head", "Department Head", dept),
                         ("auditor", "Read-only / Auditor", None)]:
        u, _ = add_member(o, f"{key}@hope.org", role_name=role)
        people[key] = u
        make_staff_profile(o, u, department=d)
    return people


def J(env, path=""):
    return f"/o/{env['org'].slug}/projects{path}"


def G(env, path=""):
    return f"/o/{env['org'].slug}/programmes{path}"


def as_(client, key):
    logout(client)
    login(client, f"{key}@hope.org")


def make_project(client, env, who="pm", team=("pof", "field"), **over):
    data = {"title": "School Water Points", "sector": "WASH", "manager_id": env["pm"].id,
            "department_id": env["dept"].id, "currency": "GHS", "approved_budget": "50000",
            "start_date": f"{YEAR}-01-01", "end_date": f"{YEAR + 1}-06-30", "objectives": "Safe water in 20 schools"}
    data.update(over)
    as_(client, who)
    r = client.post(J(env, "/new"), data=data)
    assert r.status_code == 302, r.data[:800]
    proj = Project.query.filter_by(title=data["title"]).one()
    as_(client, "pm" if proj.manager_id == env["pm"].id else who)
    for key in team:
        client.post(J(env, f"/{proj.id}/team"), data={"user_id": env[key].id, "role_label": "Team"})
    logout(client)
    return proj


def make_programme(client, env, title="Clean Water Programme"):
    as_(client, "pd")
    client.post(G(env, "/new"), data={"title": title, "manager_id": env["pd"].id, "currency": "GHS",
                                      "approved_budget": "200000", "start_date": f"{YEAR}-01-01",
                                      "end_date": f"{YEAR + 2}-12-31"})
    logout(client)
    return Programme.query.filter_by(title=title).one()


def activate(client, env, proj, approver="ed"):
    as_(client, "pm")
    client.post(J(env, f"/{proj.id}/status"), data={"status": "planned"})
    as_(client, approver)
    client.post(J(env, f"/{proj.id}/status"), data={"status": "approved"})
    client.post(J(env, f"/{proj.id}/status"), data={"status": "active"})
    logout(client)


# --- Registration and visibility ------------------------------------------------------------

def test_register_independent_and_linked(client, env, db):
    proj = make_project(client, env)
    assert proj.code == f"PRJ/{YEAR}/001" and proj.programme_id is None
    assert proj.duration_months == 18 and proj.objectives == "Safe water in 20 schools"
    assert {t.user_id for t in proj.team} == {env["pof"].id, env["field"].id}
    prog = make_programme(client, env)
    linked = make_project(client, env, who="pd", title="Borehole drilling", programme_id=prog.id, team=())
    assert linked.programme_id == prog.id and linked.code == f"PRJ/{YEAR}/002"
    assert prog.code.startswith("PRG/")  # separate numbering

    as_(client, "pd")
    html = client.get(J(env, "/?programme=none")).data.decode()
    assert "School Water Points" in html and "Borehole drilling" not in html
    html = client.get(J(env, f"/?programme={prog.id}")).data.decode()
    assert "Borehole drilling" in html and "School Water Points" not in html
    html = client.get(G(env, f"/{prog.id}")).data.decode()
    assert "Projects in this programme" in html and "Borehole drilling" in html
    html = client.get(J(env, f"/{linked.id}")).data.decode()
    assert "Part of programme" in html
    assert "Independent project" in client.get(J(env, f"/{proj.id}")).data.decode()


def test_project_own_scope(client, env, db):
    proj = make_project(client, env)
    other = make_project(client, env, title="Hand-washing stations", team=())
    as_(client, "field")
    listing = client.get(J(env, "/")).data.decode()
    assert "School Water Points" in listing and "Hand-washing" not in listing
    assert client.get(J(env, f"/{other.id}")).status_code == 404
    as_(client, "pof")  # team member: may edit own project only
    assert client.get(J(env, f"/{proj.id}/edit")).status_code == 200
    assert client.get(J(env, f"/{other.id}/edit")).status_code == 403
    as_(client, "pm2")  # another project manager cannot manage this one
    assert client.post(J(env, f"/{proj.id}/status"), data={"status": "planned"}).status_code == 403
    as_(client, "staff")
    assert client.get(J(env, "/")).status_code == 403
    as_(client, "head")
    assert client.get(J(env, f"/{proj.id}")).status_code == 200


def test_manager_cannot_approve_own_project_and_cannot_close_directly(client, env, db):
    proj = make_project(client, env)
    as_(client, "pm")
    client.post(J(env, f"/{proj.id}/status"), data={"status": "planned"})
    r = client.post(J(env, f"/{proj.id}/status"), data={"status": "approved"}, follow_redirects=True)
    assert b"cannot approve their own" in r.data
    activate(client, env, proj)
    db.session.expire_all()
    assert db.session.get(Project, proj.id).status == "active"
    as_(client, "ed")
    client.post(J(env, f"/{proj.id}/status"), data={"status": "completed"})
    r = client.post(J(env, f"/{proj.id}/status"), data={"status": "closed"}, follow_redirects=True)
    assert b"closure checklist" in r.data
    db.session.expire_all()
    assert db.session.get(Project, proj.id).status == "completed"


# --- Work breakdown structure ---------------------------------------------------------------

def test_work_breakdown_structure(client, env, db):
    proj = make_project(client, env)
    as_(client, "pof")
    client.post(J(env, f"/{proj.id}/components/new"), data={"code": "C1", "title": "Infrastructure",
                                                            "responsible_id": env["pof"].id})
    comp = Component.query.one()
    client.post(J(env, f"/{proj.id}/activities/new"), data={"title": "Drill boreholes", "component_id": comp.id,
                                                            "planned_start": TODAY, "planned_end": TODAY,
                                                            "planned_budget": "0"})
    act = Activity.query.one()
    assert act.project_id == proj.id and act.programme_id is None and act.component_id == comp.id
    client.post(J(env, f"/{proj.id}/wbs/tasks"), data={"title": "Hire drilling contractor", "activity_id": act.id,
                                                       "assigned_to_id": env["field"].id, "priority": "high"})
    parent = Task.query.one()
    assert parent.project_id == proj.id and parent.activity_id == act.id
    client.post(J(env, f"/{proj.id}/wbs/tasks"), data={"title": "Get three quotes", "parent_id": parent.id,
                                                       "priority": "normal"})
    sub = Task.query.filter_by(title="Get three quotes").one()
    assert sub.parent_id == parent.id and sub.activity_id == act.id and sub.assigned_to_id == env["pof"].id
    assert Notification.query.filter_by(user_id=env["field"].id, kind="task").count() == 1
    html = client.get(J(env, f"/{proj.id}/wbs")).data.decode()
    for text in ("Infrastructure", "Drill boreholes", "Hire drilling contractor", "Get three quotes"):
        assert text in html
    # a project team member who is not the assignee can see the task and its context
    as_(client, "pm")
    html = client.get(f"/o/{env['org'].slug}/tasks/{parent.id}").data.decode()
    assert "Drill boreholes" in html and "Get three quotes" in html and proj.code in html
    as_(client, "staff")  # not on the project
    assert client.get(f"/o/{env['org'].slug}/tasks/{parent.id}").status_code == 404
    # a component of another project cannot be used
    other = make_project(client, env, title="Other project", team=())
    as_(client, "pm")
    client.post(J(env, f"/{other.id}/activities/new"), data={"title": "X", "component_id": comp.id,
                                                             "planned_budget": "0"})
    assert not Activity.query.filter_by(title="X").first()
    # removing a component keeps its activities
    as_(client, "pof")
    client.post(J(env, f"/{proj.id}/components/{comp.id}/delete"), data={})
    db.session.expire_all()
    assert db.session.get(Activity, act.id).component_id is None
    # programmes have no work breakdown page
    prog = make_programme(client, env)
    as_(client, "pd")
    assert client.get(G(env, f"/{prog.id}/wbs")).status_code == 404


# --- Deliverables ---------------------------------------------------------------------------

def test_deliverables_submitted_and_checked_by_different_people(client, env, db):
    proj = make_project(client, env)
    as_(client, "pm")
    client.post(J(env, f"/{proj.id}/deliverables/new"), data={
        "title": "Borehole completion report", "acceptance_criteria": "Signed by district engineer",
        "due_date": TODAY, "responsible_id": env["field"].id, "priority": "high"})
    d = Deliverable.query.one()
    assert d.status == "pending"
    assert Notification.query.filter(Notification.user_id == env["field"].id,
                                     Notification.title.like("Deliverable assigned%")).count() == 1
    # the responsible field officer (no edit rights) may submit their own deliverable
    as_(client, "field")
    client.post(J(env, f"/{proj.id}/deliverables/{d.id}/submit"), data={"note": "Attached"})
    db.session.expire_all()
    d = db.session.get(Deliverable, d.id)
    assert d.status == "submitted" and d.submitted_by_id == env["field"].id
    assert client.post(J(env, f"/{proj.id}/deliverables/{d.id}/verify"), data={}).status_code == 403
    as_(client, "pm")
    r = client.post(J(env, f"/{proj.id}/deliverables/{d.id}/reject"), data={}, follow_redirects=True)
    assert b"Say what needs to change" in r.data
    client.post(J(env, f"/{proj.id}/deliverables/{d.id}/reject"), data={"note": "Engineer signature missing"})
    db.session.expire_all()
    assert db.session.get(Deliverable, d.id).status == "rejected"
    # the manager submits it themselves this time, so they cannot also accept it
    client.post(J(env, f"/{proj.id}/deliverables/{d.id}/submit"), data={})
    r = client.post(J(env, f"/{proj.id}/deliverables/{d.id}/verify"), data={}, follow_redirects=True)
    assert b"Someone other than the person who submitted" in r.data
    as_(client, "pd")
    client.post(J(env, f"/{proj.id}/deliverables/{d.id}/verify"), data={"note": "OK"})
    db.session.expire_all()
    d = db.session.get(Deliverable, d.id)
    assert d.status == "verified" and d.verified_by_id == env["pd"].id
    as_(client, "pm")
    r = client.get(J(env, f"/{proj.id}/deliverables/{d.id}/edit"), follow_redirects=True)
    assert b"verified deliverable cannot be changed" in r.data
    assert client.post(J(env, f"/{proj.id}/deliverables/{d.id}/cancel"), data={}).status_code == 400


# --- Risks and issues -----------------------------------------------------------------------

def test_risk_register_issues_and_corrective_actions(client, env, db):
    proj = make_project(client, env)
    as_(client, "pof")
    client.post(J(env, f"/{proj.id}/risks/new"), data={
        "code": "R1", "title": "Contractor delays", "category": "Partner / delivery", "probability": "4",
        "impact": "5", "status": "open", "owner_id": env["pm"].id,
        "review_date": (date.today() + timedelta(days=1)).isoformat()})
    risk = RiskItem.query.one()
    assert risk.project_id == proj.id and risk.rating == 20 and risk.level == "critical"
    assert RiskItem(probability=2, impact=3).level == "medium" and RiskItem(probability=3, impact=4).level == "high"
    client.post(J(env, f"/{proj.id}/issues/new"), data={"title": "Pump stolen", "severity": "high",
                                                        "risk_id": risk.id, "status": "open"})
    issue = Issue.query.one()
    assert issue.raised_by_id == env["pof"].id and issue.raised_on == date.today()
    client.post(J(env, f"/{proj.id}/issue/{issue.id}/actions"), data={
        "title": "Install lockable housing", "assigned_to_id": env["field"].id, "priority": "high"})
    t = Task.query.filter_by(issue_id=issue.id).one()
    assert t.project_id == proj.id and t.assigned_to_id == env["field"].id
    db.session.expire_all()
    assert db.session.get(Issue, issue.id).status == "in_progress"
    client.post(J(env, f"/{proj.id}/risk/{risk.id}/actions"), data={
        "title": "Weekly contractor check-in", "assigned_to_id": env["pm"].id})
    assert Task.query.filter_by(risk_id=risk.id).count() == 1
    r = client.post(J(env, f"/{proj.id}/issues/{issue.id}/edit"), data={"title": "Pump stolen", "severity": "high",
                                                                        "status": "resolved"})
    assert b"Describe how the issue was resolved" in r.data
    client.post(J(env, f"/{proj.id}/issues/{issue.id}/edit"), data={
        "title": "Pump stolen", "severity": "high", "status": "resolved", "resolution": "Replaced and secured"})
    db.session.expire_all()
    i = db.session.get(Issue, issue.id)
    assert i.status == "resolved" and i.resolved_on == date.today()
    html = client.get(J(env, f"/{proj.id}/risks")).data.decode()
    assert "Contractor delays" in html and "Install lockable housing" in html and "critical" in html
    # the corrective-action task is visible to the assignee and links back
    as_(client, "field")
    html = client.get(f"/o/{env['org'].slug}/tasks/{t.id}").data.decode()
    assert "Corrective action for" in html and "Pump stolen" in html
    # risk register works for programmes too
    prog = make_programme(client, env)
    as_(client, "pd")
    client.post(G(env, f"/{prog.id}/risks/new"), data={"title": "Funding cut", "category": "Financial",
                                                       "probability": "2", "impact": "5", "status": "open"})
    assert RiskItem.query.filter_by(programme_id=prog.id).one().rating == 10
    # an issue of one owner cannot be reached through another
    assert client.get(G(env, f"/{prog.id}/issues/{issue.id}/edit")).status_code == 404


# --- Closure --------------------------------------------------------------------------------

def _line(client, env, owner_url, desc, amount):
    c = BudgetCategory.query.filter_by(organization_id=env["org"].id, name="Training and workshops").one()
    client.post(owner_url + "/finance/lines", data={"b-category_id": c.id, "b-description": desc, "b-amount": amount})
    return BudgetLine.query.filter_by(description=desc).one()


def _spend(client, owner_url, line, amount, desc, kind="expenditure"):
    client.post(owner_url + "/finance/expenditure", data={
        "x-kind": kind, "x-budget_line_id": line.id, "x-spent_on": TODAY, "x-description": desc, "x-amount": str(amount)})
    return Expenditure.query.filter_by(description=desc).one()


def test_closure_checklist_approval_and_archive(client, env, db):
    proj = make_project(client, env)
    url = J(env, f"/{proj.id}")
    as_(client, "fin")
    line = _line(client, env, url, "Materials", "1000")  # budgets are locked once approved
    activate(client, env, proj)
    as_(client, "pm")
    client.post(url + "/deliverables/new", data={"title": "Final handover", "responsible_id": env["pof"].id,
                                                 "priority": "normal"})
    d = Deliverable.query.one()
    client.post(url + "/issues/new", data={"title": "Late materials", "severity": "low", "status": "open"})
    issue = Issue.query.one()
    as_(client, "fin")
    pending = _spend(client, url, line, 100, "Cement")
    as_(client, "pm")
    html = client.get(url + "/closure").data.decode()
    assert "Not yet: 1 still open" in html  # deliverable
    client.post(url + "/closure", data={"final_report": "All 20 schools served."})
    r = client.post(url + "/closure/submit", data={}, follow_redirects=True)
    assert b"Finish the open items" in r.data
    from app.blueprints.project_extras import closure_checklist
    checks = {c["key"]: c["ok"] for c in closure_checklist(db.session.get(Project, proj.id),
                                                           ProjectClosure.query.one())}
    assert checks == {"deliverables": False, "activities": True, "tasks": True, "expenditure": False,
                      "commitments": True, "issues": False, "results": True, "orders": True, "assets": True,
                      "report": False}
    # settle everything
    as_(client, "pof")
    client.post(url + f"/deliverables/{d.id}/submit", data={})
    as_(client, "pm")
    client.post(url + f"/deliverables/{d.id}/verify", data={})
    client.post(url + f"/issues/{issue.id}/edit", data={"title": "Late materials", "severity": "low",
                                                        "status": "closed", "resolution": "Delivered"})
    client.post(url + "/closure", data={"final_report": "All 20 schools served.",
                                        "financial_reconciliation": "Spent 100 of 1,000; balance returned."})
    as_(client, "fin2")
    client.post(url + f"/finance/expenditure/{pending.id}/approve", data={})
    as_(client, "pm")
    client.post(url + "/closure/submit", data={})
    c = ProjectClosure.query.one()
    assert c.status == "submitted" and c.submitted_by_id == env["pm"].id
    # the project manager cannot approve their own closure
    assert client.post(url + "/closure/approve", data={}, follow_redirects=True).data.count(
        b"must be approved by someone other") == 1
    as_(client, "ed")
    client.post(url + "/closure/approve", data={"note": "Well done"})
    db.session.expire_all()
    p = db.session.get(Project, proj.id)
    c = ProjectClosure.query.one()
    assert p.status == "closed" and p.closed_at is not None
    assert c.status == "approved" and c.approved_by_id == env["ed"].id and all(x["ok"] for x in c.checklist_snapshot)
    assert Notification.query.filter_by(user_id=env["pof"].id, title=f"{p.code} is closed").count() == 1
    # read-only archive: nothing can be changed, even by managers
    as_(client, "pm")
    assert client.get(url).status_code == 200 and b"read-only archive" in client.get(url).data
    for path, data in (("/edit", {"title": "x"}), ("/deliverables/new", {"title": "x"}),
                       (f"/deliverables/{d.id}/reopen", {}), ("/risks/new", {"title": "x"}),
                       ("/wbs/tasks", {"title": "x"}), ("/team", {"user_id": env["pof2"].id}),
                       ("/closure", {"final_report": "changed"}), ("/finance/lines", {})):
        assert client.post(url + path, data=data).status_code == 403, path
    assert client.post(url + "/status", data={"status": "active"}).status_code == 403
    as_(client, "ed")
    assert client.post(url + "/status", data={"status": "active"}).status_code == 403


def test_closed_project_tasks_are_read_only(client, env, db):
    proj = make_project(client, env)
    as_(client, "pm")
    client.post(J(env, f"/{proj.id}/wbs/tasks"), data={"title": "Survey", "assigned_to_id": env["pof"].id,
                                                       "priority": "normal"})
    t = Task.query.one()
    p = db.session.get(Project, proj.id)
    p.status = "closed"
    db.session.commit()
    as_(client, "pof")
    T = f"/o/{env['org'].slug}/tasks/{t.id}"
    assert client.get(T).status_code == 200
    assert client.post(T + "/status", data={"status": "done"}).status_code == 403
    assert client.post(T + "/comment", data={"body": "hi"}).status_code == 403
    assert client.get(T + "/edit").status_code == 403


# --- Roll-up into programmes ----------------------------------------------------------------

def _indicator(client, owner_url, **over):
    data = {"name": "People with safe water", "unit": "number", "aggregation": "sum", "direction": "increase",
            "baseline_value": "0", "target_value": "1000", "frequency": "quarterly"}
    data.update(over)
    assert client.post(owner_url + "/indicators/new", data=data).status_code == 302
    return Indicator.query.filter_by(name=data["name"]).order_by(Indicator.id.desc()).first()


def _result(client, owner_url, ind, start, end, value):
    client.post(owner_url + f"/indicators/{ind.id}", data={"what": "result", "r-period_start": start,
                                                          "r-period_end": end, "r-value": str(value)})
    return IndicatorResult.query.filter_by(indicator_id=ind.id).order_by(IndicatorResult.id.desc()).first()


def test_programme_rollup_without_double_counting(client, env, db):
    from app.exporting import report_data
    from app.programme_logic import consolidated, finance_summary, indicator_actual
    prog = make_programme(client, env)
    proj = make_project(client, env, who="pd", title="Borehole drilling", programme_id=prog.id)
    solo = make_project(client, env, title="Independent latrines")
    gurl, jurl = G(env, f"/{prog.id}"), J(env, f"/{proj.id}")
    # money: each payment belongs to exactly one owner
    as_(client, "fin")
    gl = _line(client, env, gurl, "Programme coordination", "1000")
    jl = _line(client, env, jurl, "Drilling", "500")
    sl = _line(client, env, J(env, f"/{solo.id}"), "Latrines", "700")
    e1, e2 = _spend(client, gurl, gl, 100, "Coordination meeting"), _spend(client, jurl, jl, 50, "Survey")
    e3 = _spend(client, J(env, f"/{solo.id}"), sl, 70, "Slabs")
    as_(client, "fin2")
    for e, u in ((e1, gurl), (e2, jurl), (e3, J(env, f"/{solo.id}"))):
        client.post(u + f"/finance/expenditure/{e.id}/approve", data={})
    db.session.expire_all()
    prog, proj = db.session.get(Programme, prog.id), db.session.get(Project, proj.id)
    assert finance_summary(prog)["spent"] == Decimal("100")  # programme's own figures stay its own
    assert finance_summary(proj)["spent"] == Decimal("50")
    from flask import g
    g.tenant_id = env["org"].id
    cons = consolidated(prog)
    assert cons["budget"] == Decimal("1500") and cons["spent"] == Decimal("150")  # independent project not included
    assert [r["p"].code for r in cons["projects"]] == [proj.code]

    # results: a project indicator feeds the programme indicator; each result is entered once
    as_(client, "meal")
    pind = _indicator(client, gurl, name="People reached with safe water (programme)")
    jind = _indicator(client, jurl, name="People reached with safe water (project)", contributes_to_id=pind.id)
    assert jind.contributes_to_id == pind.id
    r = client.post(jurl + "/indicators/new", data={"name": "Average yield", "unit": "number", "aggregation": "latest",
                                                    "direction": "increase", "baseline_value": "0",
                                                    "target_value": "5", "frequency": "quarterly",
                                                    "contributes_to_id": pind.id})
    assert b"Only indicators that add up" in r.data
    as_(client, "pof")
    pr = _result(client, jurl, jind, f"{YEAR}-01-01", f"{YEAR}-03-31", 300)
    as_(client, "pd")
    gr = _result(client, gurl, pind, f"{YEAR}-01-01", f"{YEAR}-03-31", 200)
    as_(client, "meal")
    db.session.expire_all()
    pind, jind = db.session.get(Indicator, pind.id), db.session.get(Indicator, jind.id)
    assert indicator_actual(pind) is None  # nothing verified yet, so no figure
    client.post(jurl + f"/indicators/{jind.id}/results/{pr.id}/verify", data={})
    client.post(gurl + f"/indicators/{pind.id}/results/{gr.id}/verify", data={})
    db.session.expire_all()
    pind, jind = db.session.get(Indicator, pind.id), db.session.get(Indicator, jind.id)
    assert indicator_actual(jind) == Decimal("300")
    assert indicator_actual(pind) == Decimal("500")
    assert indicator_actual(pind, include_projects=False) == Decimal("200")
    html = client.get(gurl + f"/indicators/{pind.id}").data.decode()
    assert "Includes projects" in html and proj.code in html
    data = report_data(prog)
    assert [p["code"] for p in data["projects"]] == [proj.code]
    assert data["consolidated"]["spent"] == 150.0
    assert next(i for i in data["indicators"] if i["name"].endswith("(programme)"))["cumulative"] == 500.0
    # Excel and PDF exports include the projects
    as_(client, "pd")
    assert client.get(gurl + "/export.xlsx").status_code == 200
    assert client.get(gurl + "/export.pdf").status_code == 200


def test_project_indicator_cannot_link_outside_its_programme(client, env, db):
    prog = make_programme(client, env)
    other = make_programme(client, env, title="Other programme")
    proj = make_project(client, env, who="pd", title="Linked", programme_id=prog.id)
    as_(client, "meal")
    foreign = _indicator(client, G(env, f"/{other.id}"), name="Other programme indicator")
    r = client.post(J(env, f"/{proj.id}/indicators/new"), data={
        "name": "Bad link", "unit": "number", "aggregation": "sum", "direction": "increase", "baseline_value": "0",
        "target_value": "5", "frequency": "quarterly", "contributes_to_id": foreign.id})
    assert r.status_code in (200, 400) and not Indicator.query.filter_by(name="Bad link").first()


# --- Isolation, support access, reminders, pages --------------------------------------------

def test_project_tenant_isolation(client, app, env, db):
    proj = make_project(client, env)
    proj2 = make_project(client, env, title="Second project")
    as_(client, "pm")
    client.post(J(env, f"/{proj2.id}/deliverables/new"), data={"title": "Other deliverable", "priority": "normal"})
    d2 = Deliverable.query.one()
    assert client.post(J(env, f"/{proj.id}/deliverables/{d2.id}/submit"), data={}).status_code == 404
    o2, _ = make_org("Rival Org", admin_email="admin@rival.org")
    other = app.test_client()
    login(other, "admin@rival.org")
    for path in (f"/{proj.id}", f"/{proj.id}/wbs", f"/{proj.id}/deliverables", f"/{proj.id}/closure"):
        assert other.get(f"/o/{o2.slug}/projects{path}").status_code == 404, path
    # a programme id is not a project id: each blueprint loads only its own kind
    assert Programme.query.count() == 0
    assert client.get(G(env, f"/{proj.id}")).status_code == 404


def test_support_access_read_only_on_projects(client, env, db):
    from app.models import PlatformRole, SupportAccessRequest, User, utcnow
    from tests.conftest import make_staff
    proj = make_project(client, env)
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    req = SupportAccessRequest(organization_id=env["org"].id, reason="Checking closure problem",
                               requested_by_id=User.query.filter_by(email="support@holido.org").one().id,
                               duration_minutes=30, status="approved", starts_at=utcnow(),
                               expires_at=utcnow() + timedelta(minutes=30))
    db.session.add(req)
    db.session.commit()
    login(client, "support@holido.org")
    client.post(f"/platform/support/{req.id}/enter")
    for path in ("", "/wbs", "/deliverables", "/risks", "/closure"):
        assert client.get(J(env, f"/{proj.id}{path}")).status_code == 200, path
    assert client.post(J(env, f"/{proj.id}/risks/new"), data={"title": "x"}).status_code == 403
    assert client.post(J(env, f"/{proj.id}/closure"), data={"final_report": "x"}).status_code == 403


def test_project_reminders_and_calendar(client, app, env, db):
    proj = make_project(client, env)
    soon = date.today() + timedelta(days=1)
    db.session.add_all([
        Activity(organization_id=env["org"].id, project_id=proj.id, title="Community meeting", planned_start=soon,
                 responsible_id=env["field"].id),
        Deliverable(organization_id=env["org"].id, project_id=proj.id, title="Baseline report", due_date=soon,
                    responsible_id=env["pof"].id),
        RiskItem(organization_id=env["org"].id, project_id=proj.id, title="Flooding", review_date=soon,
                 owner_id=env["pm"].id)])
    db.session.commit()
    runner = app.test_cli_runner()
    runner.invoke(args=["oims", "send-reminders"])
    runner.invoke(args=["oims", "send-reminders"])  # no duplicates
    for key in ("field", "pof", "pm"):
        assert Notification.query.filter_by(user_id=env[key].id, kind="reminder").count() == 1, key
    note = Notification.query.filter_by(user_id=env["field"].id, kind="reminder").one()
    assert "/projects/" in note.link
    as_(client, "pm")
    html = client.get(f"/o/{env['org'].slug}/calendar?month={soon:%Y-%m}&scope=organization").data.decode()
    assert "Activity: Community meeting" in html and "Deliverable due: Baseline report" in html
    assert "Risk review: Flooding" in html
    as_(client, "pof")
    html = client.get(f"/o/{env['org'].slug}/").data.decode()
    assert "Baseline report" in html  # dashboard deadlines


def test_all_project_pages_render(client, env, db):
    prog = make_programme(client, env)
    proj = make_project(client, env, who="pd", programme_id=prog.id)
    as_(client, "pm")
    client.post(J(env, f"/{proj.id}/components/new"), data={"title": "Component A"})
    comp = Component.query.one()
    client.post(J(env, f"/{proj.id}/deliverables/new"), data={"title": "D1", "priority": "normal"})
    d = Deliverable.query.one()
    client.post(J(env, f"/{proj.id}/risks/new"), data={"title": "R", "category": "Operational", "probability": "3",
                                                       "impact": "3", "status": "open"})
    r = RiskItem.query.one()
    client.post(J(env, f"/{proj.id}/issues/new"), data={"title": "I", "severity": "low", "status": "open"})
    i = Issue.query.one()
    client.post(J(env, f"/{proj.id}/activities/new"), data={"title": "A1", "planned_budget": "0",
                                                            "planned_start": TODAY, "planned_end": TODAY})
    a = Activity.query.one()
    pages = ("/", "/new", f"/{proj.id}", f"/{proj.id}/edit", f"/{proj.id}/planning", f"/{proj.id}/team",
             f"/{proj.id}/wbs", f"/{proj.id}/components/new", f"/{proj.id}/components/{comp.id}/edit",
             f"/{proj.id}/deliverables", f"/{proj.id}/deliverables/new", f"/{proj.id}/deliverables/{d.id}/edit",
             f"/{proj.id}/risks", f"/{proj.id}/risks/new", f"/{proj.id}/risks/{r.id}/edit", f"/{proj.id}/issues/new",
             f"/{proj.id}/issues/{i.id}/edit", f"/{proj.id}/closure", f"/{proj.id}/results",
             f"/{proj.id}/indicators", f"/{proj.id}/workplans",
             f"/{proj.id}/activities/new", f"/{proj.id}/activities/{a.id}", f"/{proj.id}/activities/{a.id}/edit",
             f"/{proj.id}/finance", f"/{proj.id}/monitoring", f"/{proj.id}/reports", f"/{proj.id}/reports/new")
    for path in pages:
        assert client.get(J(env, path)).status_code == 200, path
    as_(client, "pd")
    for path in ("/new?programme=%d" % prog.id, f"/{proj.id}", f"/{proj.id}/closure", f"/{proj.id}/indicators/new"):
        assert client.get(J(env, path)).status_code == 200, path
    for path in (f"/{prog.id}", f"/{prog.id}/risks", f"/{prog.id}/risks/new", f"/{prog.id}/issues/new"):
        assert client.get(G(env, path)).status_code == 200, path
    assert client.get(f"/o/{env['org'].slug}/calendar").status_code == 200
    as_(client, "auditor")
    for path in (f"/{proj.id}", f"/{proj.id}/wbs", f"/{proj.id}/deliverables", f"/{proj.id}/risks",
                 f"/{proj.id}/closure"):
        assert client.get(J(env, path)).status_code == 200, path
    html = client.get(J(env, f"/{proj.id}/deliverables")).data.decode()
    assert "Submit for checking" not in html and "Deliverable</a>" not in html
    assert client.post(J(env, f"/{proj.id}/risks/new"), data={"title": "x"}).status_code == 403
