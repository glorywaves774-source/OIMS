"""Phase 6: procurement (request → quotations → order → receipt → payment), suppliers, assets, finance overview."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import (Asset, AuditLog, BudgetCategory, BudgetLine, Expenditure, Notification, Project,
                        PurchaseOrder, PurchaseRequest, Supplier)
from tests.conftest import add_member, login, logout, make_department, make_org, make_staff_profile

YEAR = date.today().year
TODAY = date.today().isoformat()


@pytest.fixture
def env(app, db):
    o, admin = make_org("Hope Trust", admin_email="admin@hope.org")
    dept = make_department(o, "Programmes")
    people = {"org": o, "dept": dept, "admin": admin}
    for key, role in [("pd", "Programme Director"), ("pm", "Project Manager"), ("pof", "Project Officer"),
                      ("pof2", "Project Officer"), ("proc", "Procurement Officer"), ("fin", "Finance Officer"),
                      ("fin2", "Finance Officer"), ("ed", "Executive Director"), ("logi", "Logistics & Assets Officer"),
                      ("staff", "Staff Member"), ("head", "Department Head"), ("auditor", "Read-only / Auditor")]:
        u, _ = add_member(o, f"{key}@hope.org", role_name=role)
        people[key] = u
        make_staff_profile(o, u, department=dept if key in ("pm", "pof", "head") else None)
    return people


def W(env, path):
    return f"/o/{env['org'].slug}{path}"


def as_(client, key):
    logout(client)
    login(client, f"{key}@hope.org")


@pytest.fixture
def proj(client, env, db):
    as_(client, "pd")
    client.post(W(env, "/projects/new"), data={"title": "School Water", "manager_id": env["pm"].id, "currency": "GHS",
                                                "approved_budget": "20000", "department_id": env["dept"].id})
    p = Project.query.one()
    as_(client, "pm")
    client.post(W(env, f"/projects/{p.id}/team"), data={"user_id": env["pof"].id})
    as_(client, "fin")
    cat = BudgetCategory.query.filter_by(organization_id=env["org"].id, name="Training and workshops").one()
    client.post(W(env, f"/projects/{p.id}/finance/lines"), data={"b-category_id": cat.id, "b-description": "Equipment",
                                                                 "b-amount": "10000"})
    as_(client, "pm")
    client.post(W(env, f"/projects/{p.id}/status"), data={"status": "planned"})
    as_(client, "ed")
    client.post(W(env, f"/projects/{p.id}/status"), data={"status": "approved"})
    client.post(W(env, f"/projects/{p.id}/status"), data={"status": "active"})
    logout(client)
    db.session.expire_all()
    p = db.session.get(Project, p.id)
    assert p.status == "active"
    return p


def suppliers(client, env, names=("Alpha Tech", "Beta Supplies", "Gamma Stores")):
    as_(client, "proc")
    for n in names:
        client.post(W(env, "/procurement/suppliers/new"), data={"name": n, "category": "IT equipment",
                                                                 "bank_account": "0012345678"})
    return [Supplier.query.filter_by(name=n).one() for n in names]


def make_request(client, env, proj, who="pof", items=(("Laptop", "2", "3000", True), ("Printer", "1", "500", False))):
    as_(client, who)
    line = BudgetLine.query.filter_by(project_id=proj.id).one()
    r = client.post(W(env, "/procurement/new"), data={"owner": f"project:{proj.id}", "title": "Field office equipment",
                                                       "budget_line_id": line.id, "justification": "Staff need laptops"})
    assert r.status_code == 302, r.data[:300]
    pr = PurchaseRequest.query.order_by(PurchaseRequest.id.desc()).first()
    for desc, qty, cost, asset in items:
        data = {"i-description": desc, "i-quantity": qty, "i-unit": "each", "i-unit_cost": cost}
        if asset:
            data.update({"i-is_asset": "y", "i-asset_category": "Computers and IT"})
        client.post(W(env, f"/procurement/{pr.id}/items"), data=data)
    return pr


def test_full_purchase_flow(client, env, db, proj):
    from app.programme_logic import finance_summary, line_figures
    a, b, c = suppliers(client, env)
    pr = make_request(client, env, proj)
    assert pr.code == f"PR/{YEAR}/0001" and pr.estimated_total == Decimal("6500.00")
    client.post(W(env, f"/procurement/{pr.id}/submit"), data={})
    db.session.expire_all()
    pr = db.session.get(PurchaseRequest, pr.id)
    assert pr.status == "submitted" and pr.method == "quotes"   # 6,500 is above the 5,000 threshold
    r = client.post(W(env, f"/procurement/{pr.id}/approve"), data={}, follow_redirects=True)
    assert b"other than the requester" in r.data
    as_(client, "pm")  # the project manager approves requests for own projects
    client.post(W(env, f"/procurement/{pr.id}/approve"), data={})
    # quotations: three needed, the lowest unless explained
    as_(client, "proc")
    for s, amt in ((a, "6400"), (b, "6200")):
        client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": s.id, "q-received_on": TODAY,
                                                                       "q-total_amount": amt})
    db.session.expire_all()
    pr = db.session.get(PurchaseRequest, pr.id)
    qa = next(q for q in pr.quotations if q.supplier_id == a.id)
    r = client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": qa.id}, follow_redirects=True)
    assert b"record 3 quotations" in r.data
    client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": c.id, "q-received_on": TODAY,
                                                                   "q-total_amount": "6600"})
    r = client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": qa.id}, follow_redirects=True)
    assert b"not the lowest" in r.data
    client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": qa.id,
                                                               "s-selection_reason": "Two-year warranty; B has none"})
    db.session.expire_all()
    pr = db.session.get(PurchaseRequest, pr.id)
    assert pr.selected_quotation.supplier_id == a.id
    laptop, printer = pr.items
    r = client.post(W(env, f"/procurement/{pr.id}/order"), data={"order_date": TODAY, f"price_{laptop.id}": "3000",
                                                                  f"price_{printer.id}": "500"}, follow_redirects=True)
    assert b"cannot be more than the chosen quotation" in r.data
    client.post(W(env, f"/procurement/{pr.id}/order"), data={"order_date": TODAY, f"price_{laptop.id}": "2950",
                                                              f"price_{printer.id}": "450"})
    po = PurchaseOrder.query.one()
    assert po.total == Decimal("6350.00") and po.status == "draft"
    # the procurement officer cannot approve (no finance approval); finance approves and the money is committed
    assert client.post(W(env, f"/procurement/orders/{po.id}/approve"), data={}).status_code == 403
    as_(client, "fin")
    client.post(W(env, f"/procurement/orders/{po.id}/approve"), data={})
    db.session.expire_all()
    po = db.session.get(PurchaseOrder, po.id)
    line = db.session.get(BudgetLine, po.request.budget_line_id)
    assert po.status == "approved" and po.commitment.amount == Decimal("6350.00") and po.request.status == "ordered"
    assert line_figures(line)["available"] == Decimal("3650.00")
    # goods received in two parts; laptops become assets
    as_(client, "pof")   # the requester confirms what arrived
    lap, prt = po.items
    r = client.post(W(env, f"/procurement/orders/{po.id}/receive"), data={"received_on": TODAY, f"qty_{lap.id}": "3"},
                    follow_redirects=True)
    assert b"can still be received" in r.data
    client.post(W(env, f"/procurement/orders/{po.id}/receive"), data={"received_on": TODAY, f"qty_{lap.id}": "1",
                                                                       f"qty_{prt.id}": "1"})
    db.session.expire_all()
    po = db.session.get(PurchaseOrder, po.id)
    assert po.status == "partially_received" and po.received_value == Decimal("3400.00")
    assets = Asset.query.all()
    assert len(assets) == 1 and assets[0].project_id == proj.id and assets[0].cost == Decimal("2950.00")
    assert assets[0].status == "in_store" and assets[0].order_id == po.id
    # pay: never more than the value received
    as_(client, "fin")
    r = client.post(W(env, f"/procurement/orders/{po.id}/pay"), data={"amount": "4000", "paid_on": TODAY,
                                                                      "reference": "INV-1"}, follow_redirects=True)
    assert b"cannot exceed the value of goods" in r.data
    client.post(W(env, f"/procurement/orders/{po.id}/pay"), data={"amount": "3400", "paid_on": TODAY,
                                                                  "reference": "INV-1"})
    pay1 = Expenditure.query.filter_by(purchase_order_id=po.id, kind="expenditure").one()
    url = W(env, f"/projects/{proj.id}/finance/expenditure/{pay1.id}/approve")
    r = client.post(url, data={}, follow_redirects=True)
    assert b"different person must approve" in r.data
    as_(client, "fin2")
    client.post(url, data={})
    db.session.expire_all()
    po = db.session.get(PurchaseOrder, po.id)
    fs = finance_summary(db.session.get(Project, proj.id))
    assert fs["spent"] == Decimal("3400.00") and fs["committed"] == Decimal("2950.00")
    assert fs["available"] == Decimal("3650.00")   # paying did not use the money twice
    # the rest arrives and is paid; the order closes and the commitment is gone
    as_(client, "proc")
    client.post(W(env, f"/procurement/orders/{po.id}/receive"), data={"received_on": TODAY, f"qty_{lap.id}": "1"})
    as_(client, "fin")
    client.post(W(env, f"/procurement/orders/{po.id}/pay"), data={"amount": "2950", "paid_on": TODAY,
                                                                  "reference": "INV-2"})
    pay2 = Expenditure.query.filter_by(purchase_order_id=po.id, kind="expenditure", status="pending").one()
    as_(client, "fin2")
    client.post(W(env, f"/projects/{proj.id}/finance/expenditure/{pay2.id}/approve"), data={})
    db.session.expire_all()
    po = db.session.get(PurchaseOrder, po.id)
    fs = finance_summary(db.session.get(Project, proj.id))
    assert po.status == "closed" and po.request.status == "completed"
    assert fs["spent"] == Decimal("6350.00") and fs["committed"] == Decimal("0") and fs["available"] == Decimal("3650.00")
    assert Asset.query.count() == 2
    assert AuditLog.query.filter_by(action="finance.commitment_released").count() == 2


def test_funds_check_and_tender_rules(client, env, db, proj):
    a, b, c = suppliers(client, env)
    big = make_request(client, env, proj, items=(("Vehicle", "1", "12000", True),))
    client.post(W(env, f"/procurement/{big.id}/submit"), data={})
    as_(client, "pm")
    r = client.post(W(env, f"/procurement/{big.id}/approve"), data={}, follow_redirects=True)
    assert b"Not enough left on the budget line" in r.data
    r = client.post(W(env, f"/procurement/{big.id}/reject"), data={}, follow_redirects=True)
    assert b"Say why" in r.data
    client.post(W(env, f"/procurement/{big.id}/reject"), data={"note": "Over budget"})
    # thresholds are an organization setting
    as_(client, "pof")
    assert client.get(W(env, "/procurement/settings")).status_code == 403
    as_(client, "proc")
    client.post(W(env, "/procurement/settings"), data={"proc_quotes_threshold": "1000", "proc_tender_threshold": "5000"})
    pr = make_request(client, env, proj, items=(("Generator", "1", "6000", True),))
    client.post(W(env, f"/procurement/{pr.id}/submit"), data={})
    as_(client, "pm")
    client.post(W(env, f"/procurement/{pr.id}/approve"), data={})
    db.session.expire_all()
    pr = db.session.get(PurchaseRequest, pr.id)
    assert pr.method == "tender"
    as_(client, "proc")
    for s, amt in ((a, "5800"), (b, "5900"), (c, "5950")):
        client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": s.id, "q-received_on": TODAY,
                                                                       "q-total_amount": amt})
    low = min(db.session.get(PurchaseRequest, pr.id).quotations, key=lambda q: q.total_amount)
    r = client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": low.id}, follow_redirects=True)
    assert b"evaluation committee" in r.data
    client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": low.id,
                                                               "s-evaluation_report": "Committee met on 3 Nov."})
    db.session.expire_all()
    assert db.session.get(PurchaseRequest, pr.id).selected_quotation_id == low.id


def test_suppliers_blacklist_and_encrypted_bank_details(client, env, db, proj):
    a, b, c = suppliers(client, env)
    assert "0012345678" not in (a.bank_account_enc or "")
    as_(client, "proc")
    r = client.post(W(env, f"/procurement/suppliers/{b.id}"), data={"status": "blacklisted"}, follow_redirects=True)
    assert b"Give a reason" in r.data
    client.post(W(env, f"/procurement/suppliers/{b.id}"), data={"status": "blacklisted", "status_reason": "Fraud"})
    pr = make_request(client, env, proj, items=(("Chair", "2", "100", False),))
    client.post(W(env, f"/procurement/{pr.id}/submit"), data={})
    as_(client, "pm")
    client.post(W(env, f"/procurement/{pr.id}/approve"), data={})
    as_(client, "proc")
    client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": b.id, "q-received_on": TODAY,
                                                                   "q-total_amount": "150"})
    db.session.expire_all()
    assert db.session.get(PurchaseRequest, pr.id).quotations == []
    assert b"0012345678" in client.get(W(env, f"/procurement/suppliers/{a.id}")).data
    as_(client, "pof")  # can see the supplier, not its bank details
    html = client.get(W(env, f"/procurement/suppliers/{a.id}")).data.decode()
    assert "Alpha Tech" in html and "0012345678" not in html


def test_cancel_order_releases_commitment(client, env, db, proj):
    from app.programme_logic import finance_summary
    a, = suppliers(client, env, names=("Alpha Tech",))
    pr = make_request(client, env, proj, items=(("Chair", "4", "100", False),))
    client.post(W(env, f"/procurement/{pr.id}/submit"), data={})
    as_(client, "pm")
    client.post(W(env, f"/procurement/{pr.id}/approve"), data={})
    as_(client, "proc")
    client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": a.id, "q-received_on": TODAY,
                                                                   "q-total_amount": "400"})
    pr = db.session.get(PurchaseRequest, pr.id)
    client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": pr.quotations[0].id})
    client.post(W(env, f"/procurement/{pr.id}/order"), data={"order_date": TODAY, f"price_{pr.items[0].id}": "100"})
    po = PurchaseOrder.query.one()
    as_(client, "fin")
    client.post(W(env, f"/procurement/orders/{po.id}/approve"), data={})
    db.session.expire_all()
    assert finance_summary(db.session.get(Project, proj.id))["committed"] == Decimal("400.00")
    com = db.session.get(PurchaseOrder, po.id).commitment
    r = client.post(W(env, f"/projects/{proj.id}/finance/expenditure/{com.id}/cancel"), data={}, follow_redirects=True)
    assert b"Cancel the order instead" in r.data
    as_(client, "proc")
    r = client.post(W(env, f"/procurement/orders/{po.id}/cancel"), data={}, follow_redirects=True)
    assert b"Give a reason" in r.data
    client.post(W(env, f"/procurement/orders/{po.id}/cancel"), data={"reason": "Supplier cannot deliver"})
    db.session.expire_all()
    po = db.session.get(PurchaseOrder, po.id)
    assert po.status == "cancelled" and po.request.status == "approved"
    assert finance_summary(db.session.get(Project, proj.id))["committed"] == Decimal("0")


def test_request_visibility(client, env, db, proj):
    pr = make_request(client, env, proj)
    as_(client, "pof2")   # a project officer not on this project
    assert client.get(W(env, f"/procurement/{pr.id}")).status_code == 404
    assert client.get(W(env, "/procurement/new")).status_code == 403
    as_(client, "head")   # department head: project is in their department
    assert client.get(W(env, f"/procurement/{pr.id}")).status_code == 200
    as_(client, "staff")
    assert client.get(W(env, "/procurement/")).status_code == 403
    as_(client, "pof")
    r = client.post(W(env, "/procurement/new"), data={"owner": f"project:{proj.id}", "title": "x",
                                                       "budget_line_id": 999999, "justification": "y"})
    assert r.status_code in (200, 404)


# --- Assets ----------------------------------------------------------------------------------

def test_asset_register_lifecycle(client, env, db, proj):
    as_(client, "logi")
    client.post(W(env, "/assets/new"), data={
        "name": "Toyota Hilux", "category": "Vehicles", "serial_number": "CH-123", "purchase_date": f"{YEAR - 1}-01-15",
        "cost": "60000", "currency": "GHS", "residual_value": "0", "owner": f"project:{proj.id}", "condition": "good"})
    car = Asset.query.one()
    assert car.code == f"AST/{YEAR}/0001" and car.useful_life_years == 5 and car.status == "in_store"
    r = client.post(W(env, "/assets/new"), data={"name": "Other", "category": "Vehicles", "serial_number": "CH-123",
                                                   "currency": "GHS", "condition": "good"})
    assert b"already has this serial number" in r.data
    client.post(W(env, f"/assets/{car.id}/assign"), data={"a-to_user_id": env["staff"].id, "a-happened_on": TODAY})
    db.session.expire_all()
    car = db.session.get(Asset, car.id)
    assert car.custodian_id == env["staff"].id and car.status == "in_use"
    assert Notification.query.filter_by(user_id=env["staff"].id, kind="asset").count() == 1
    # the custodian sees it under "in my care", nothing else
    client.post(W(env, "/assets/new"), data={"name": "Desk", "category": "Furniture", "currency": "GHS",
                                              "condition": "good"})
    as_(client, "staff")
    html = client.get(W(env, "/assets/?view=mine")).data.decode()
    assert "Toyota Hilux" in html
    assert "Desk" not in client.get(W(env, "/assets/")).data.decode()
    assert client.get(W(env, f"/assets/{car.id}/edit")).status_code == 403
    as_(client, "logi")
    client.post(W(env, f"/assets/{car.id}/maintenance"), data={"e-happened_on": TODAY, "e-note": "Oil change",
                                                               "e-cost": "450", "e-next_due": (date.today() + timedelta(days=90)).isoformat()})
    client.post(W(env, f"/assets/{car.id}/verify"), data={"e-happened_on": TODAY})
    client.post(W(env, f"/assets/{car.id}/transfer"), data={"t-owner": "", "t-happened_on": TODAY,
                                                            "t-note": "Project ended"})
    db.session.expire_all()
    car = db.session.get(Asset, car.id)
    assert car.project_id is None and car.last_verified_on == date.today()
    assert [e.kind for e in car.history][:3] == ["transferred", "verified", "maintenance"]
    # disposal: requested by one person, decided by another with approval rights
    client.post(W(env, f"/assets/{car.id}/dispose"), data={"d-disposal_method": "sale", "d-disposal_value": "20000",
                                                           "d-disposal_reason": "Too costly to run"})
    r = client.post(W(env, f"/assets/{car.id}/decide"), data={"decision": "approve"})
    assert r.status_code == 403
    as_(client, "ed")
    client.post(W(env, f"/assets/{car.id}/decide"), data={"decision": "approve", "note": "Board agreed"})
    db.session.expire_all()
    car = db.session.get(Asset, car.id)
    assert car.status == "disposed" and car.disposal_approved_by_id == env["ed"].id and car.custodian_id is None
    as_(client, "logi")
    assert client.get(W(env, f"/assets/{car.id}/edit")).status_code == 403   # disposed assets are read-only


def test_depreciation():
    a = Asset(cost=Decimal("12000"), residual_value=Decimal("0"), useful_life_years=5,
              purchase_date=date(2024, 1, 10))
    assert a.book_value(date(2024, 1, 31)) == Decimal("12000.00")
    assert a.book_value(date(2025, 1, 10)) == Decimal("9600.00")      # 12 of 60 months
    assert a.book_value(date(2030, 6, 1)) == Decimal("0.00")
    b = Asset(cost=Decimal("1000"), residual_value=Decimal("100"), useful_life_years=3, purchase_date=date(2024, 1, 1))
    assert b.book_value(date(2028, 1, 1)) == Decimal("100.00")


def test_closure_waits_for_orders_and_assets(client, env, db, proj):
    from app.blueprints.project_extras import closure_checklist
    from flask import g
    as_(client, "logi")
    client.post(W(env, "/assets/new"), data={"name": "Laptop", "category": "Computers and IT", "currency": "GHS",
                                              "owner": f"project:{proj.id}", "condition": "good"})
    g.tenant_id = env["org"].id
    checks = {c["key"]: c["ok"] for c in closure_checklist(db.session.get(Project, proj.id))}
    assert checks["assets"] is False and checks["orders"] is True
    a = Asset.query.one()
    client.post(W(env, f"/assets/{a.id}/transfer"), data={"t-owner": "", "t-happened_on": TODAY, "t-note": "Handover"})
    db.session.expire_all()
    checks = {c["key"]: c["ok"] for c in closure_checklist(db.session.get(Project, proj.id))}
    assert checks["assets"] is True


# --- Overview, isolation, support, pages ------------------------------------------------------

def test_finance_overview_queue(client, env, db, proj):
    a, = suppliers(client, env, names=("Alpha Tech",))
    pr = make_request(client, env, proj, items=(("Chair", "4", "100", False),))
    client.post(W(env, f"/procurement/{pr.id}/submit"), data={})
    as_(client, "pm")
    client.post(W(env, f"/procurement/{pr.id}/approve"), data={})
    as_(client, "proc")
    client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": a.id, "q-received_on": TODAY,
                                                                   "q-total_amount": "400"})
    pr = db.session.get(PurchaseRequest, pr.id)
    client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": pr.quotations[0].id})
    client.post(W(env, f"/procurement/{pr.id}/order"), data={"order_date": TODAY, f"price_{pr.items[0].id}": "100"})
    po = PurchaseOrder.query.one()
    as_(client, "fin")
    html = client.get(W(env, "/finance/")).data.decode()
    assert po.code in html and "Waiting for your approval" in html and "GHS 10,000.00" in html
    as_(client, "staff")
    assert client.get(W(env, "/finance/")).status_code == 403


def test_procurement_isolation_and_support(client, app, env, db, proj):
    from app.models import PlatformRole, SupportAccessRequest, User, utcnow
    from tests.conftest import make_staff
    pr = make_request(client, env, proj)
    as_(client, "logi")
    client.post(W(env, "/assets/new"), data={"name": "Desk", "category": "Furniture", "currency": "GHS",
                                              "condition": "good"})
    asset = Asset.query.one()
    o2, _ = make_org("Rival Org", admin_email="admin@rival.org")
    other = app.test_client()
    login(other, "admin@rival.org")
    assert other.get(f"/o/{o2.slug}/procurement/{pr.id}").status_code == 404
    assert other.get(f"/o/{o2.slug}/assets/{asset.id}").status_code == 404
    from app.tenancy import clear_tenant
    clear_tenant()   # make_org above leaves the rival organization as the current tenant
    make_staff("support@holido.org", PlatformRole.SUPPORT_OFFICER)
    req = SupportAccessRequest(organization_id=env["org"].id, reason="Checking a purchase problem",
                               requested_by_id=User.query.filter_by(email="support@holido.org").one().id,
                               duration_minutes=30, status="approved", starts_at=utcnow(),
                               expires_at=utcnow() + timedelta(minutes=30))
    db.session.add(req)
    db.session.commit()
    logout(client)
    login(client, "support@holido.org")
    client.post(f"/platform/support/{req.id}/enter")
    assert client.get(W(env, f"/procurement/{pr.id}")).status_code == 200
    assert client.get(W(env, f"/assets/{asset.id}")).status_code == 200
    assert client.post(W(env, f"/procurement/{pr.id}/submit"), data={}).status_code == 403
    assert client.post(W(env, f"/assets/{asset.id}/verify"), data={"e-happened_on": TODAY}).status_code == 403


def test_all_phase6_pages_render(client, env, db, proj):
    a, = suppliers(client, env, names=("Alpha Tech",))
    pr = make_request(client, env, proj, items=(("Laptop", "1", "300", True),))
    client.post(W(env, f"/procurement/{pr.id}/submit"), data={})
    as_(client, "pm")
    client.post(W(env, f"/procurement/{pr.id}/approve"), data={})
    as_(client, "proc")
    client.post(W(env, f"/procurement/{pr.id}/quotations"), data={"q-supplier_id": a.id, "q-received_on": TODAY,
                                                                   "q-total_amount": "300"})
    pr = db.session.get(PurchaseRequest, pr.id)
    client.post(W(env, f"/procurement/{pr.id}/select"), data={"s-quotation_id": pr.quotations[0].id})
    client.post(W(env, f"/procurement/{pr.id}/order"), data={"order_date": TODAY, f"price_{pr.items[0].id}": "300"})
    po = PurchaseOrder.query.one()
    as_(client, "fin")
    client.post(W(env, f"/procurement/orders/{po.id}/approve"), data={})
    as_(client, "proc")
    client.post(W(env, f"/procurement/orders/{po.id}/receive"), data={"received_on": TODAY,
                                                                       f"qty_{po.items[0].id}": "1"})
    asset = Asset.query.one()
    pages = ["/procurement/", "/procurement/?view=approve", "/procurement/new", f"/procurement/new?owner=project:{proj.id}",
             f"/procurement/{pr.id}", f"/procurement/orders/{po.id}", "/procurement/suppliers/",
             "/procurement/suppliers/new", f"/procurement/suppliers/{a.id}", f"/procurement/suppliers/{a.id}/edit",
             "/procurement/settings", "/assets/", "/assets/?view=verify", "/assets/new", f"/assets/{asset.id}",
             f"/assets/{asset.id}/edit", "/finance/", f"/projects/{proj.id}/closure"]
    for p in pages:
        assert client.get(W(env, p)).status_code == 200, p
    assert client.get(W(env, "/assets/export.xlsx")).status_code == 200
    for key in ("auditor", "ed", "fin"):
        as_(client, key)
        for p in ("/procurement/", f"/procurement/{pr.id}", f"/procurement/orders/{po.id}", "/assets/", "/finance/"):
            assert client.get(W(env, p)).status_code == 200, (key, p)
