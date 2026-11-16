"""ZENTAVA Assistant: answers from the guide, role-aware links, privacy before the AI service."""
import io
import json
import urllib.error

import pytest

from app import assistant
from app.rbac import CATALOG
from tests.conftest import add_member, login, logout, make_org, make_staff


def ask(client, url, q):
    return client.post(url, json={"question": q})


@pytest.fixture
def org(app, db):
    o, admin = make_org("Help Trust", admin_email="admin@help.org")
    add_member(o, "staff@help.org", "Staff Member")
    from app.tenancy import clear_tenant
    clear_tenant()
    return o


def test_guides_are_complete_and_links_are_real(app):
    codes = {f"{m}.{a}" for m, (_, acts) in CATALOG.items() for a, _ in acts}
    with app.app_context():
        en, fr = assistant.guide("en"), assistant.guide("fr")
        assert len(en) == len(fr) >= 20
        endpoints = {r.endpoint for r in app.url_map.iter_rules()}
        for e, f in zip(en, fr):
            assert [(ep, p) for _, ep, p in e["links"]] == [(ep, p) for _, ep, p in f["links"]], e["title"]
            for _, ep, perm in e["links"]:
                assert ep in endpoints, ep
                assert perm in codes or perm in (None, "platform"), perm
            assert e["body"] and f["body"] and e["who"] and f["who"]


def test_finds_the_right_section(app):
    with app.app_context():
        assert assistant.search("How do I request leave?", "en")[0]["title"] == "Leave"
        assert assistant.search("Comment demander un congé ?", "fr")[0]["title"] == "Congés"
        assert assistant.search("exchange rate for dollars", "en")[0]["title"] == "Exchange rates"
        assert assistant.search("zzz qqq", "en") == []


def test_answers_from_the_guide_with_links_for_the_role(client, org):
    login(client, "admin@help.org")
    r = ask(client, f"/o/{org.slug}/assistant/ask", "How do I see the finance overview and approve expenditure?")
    data = r.get_json()
    assert r.status_code == 200 and data["source"] == "guide"
    assert any(l["url"] == f"/o/{org.slug}/finance/" for l in data["links"])
    logout(client)
    login(client, "staff@help.org")
    data = ask(client, f"/o/{org.slug}/assistant/ask", "How do I see the finance overview and approve expenditure?").get_json()
    assert not any("/finance/" in l["url"] for l in data["links"])       # not this role's pages
    assert "Who does this:" in data["answer"]                              # names the right role instead
    data = ask(client, f"/o/{org.slug}/assistant/ask", "how do i request leave").get_json()
    assert any(l["url"].endswith("/leave/request") or "/leave/" in l["url"] for l in data["links"])


def test_nothing_found_and_french(client, org):
    login(client, "admin@help.org")
    data = ask(client, f"/o/{org.slug}/assistant/ask", "zzz qqq").get_json()
    assert "could not find" in data["answer"] and data["links"] == []
    client.post("/language", data={"lang": "fr", "next": "/"})
    data = ask(client, f"/o/{org.slug}/assistant/ask", "Comment demander un congé ?").get_json()
    assert "Demandez un congé" in data["answer"] or "Demander un congé" in data["answer"]
    assert any(l["label"] == "Demander un congé" for l in data["links"])


def test_redaction():
    text = ("Call me on +233 24 412 3456 or 0244123456, email ama.mensah@example.org, "
            "Ghana Card GHA-123456789-0, account 00123456789, staff ID HR-2024-00017")
    out = assistant.redact(text)
    for secret in ("412 3456", "0244123456", "ama.mensah@example.org", "GHA-123456789-0", "00123456789",
                   "HR-2024-00017"):
        assert secret not in out
    assert "[email]" in out and "[ID number]" in out


def test_ai_service_gets_only_the_guide_and_a_cleaned_question(client, org, app, monkeypatch):
    sent = {}

    class Resp:
        def __init__(self, body):
            self.body = body

        def read(self):
            return self.body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout):
        sent["url"] = req.full_url
        sent["headers"] = dict(req.headers)
        sent["body"] = json.loads(req.data.decode())
        return Resp(json.dumps({"content": [{"type": "text", "text": "Open Leave and choose Request leave."}]}).encode())

    monkeypatch.setattr(assistant.urllib.request, "urlopen", fake_urlopen)
    app.config["HELP_AI_API_KEY"] = "sk-test"
    try:
        login(client, "admin@help.org")
        data = ask(client, f"/o/{org.slug}/assistant/ask",
                   "How do I request leave? My phone is 0244123456 and my email is admin@help.org").get_json()
    finally:
        app.config["HELP_AI_API_KEY"] = None
    assert data["source"] == "ai" and data["answer"] == "Open Leave and choose Request leave."
    payload = json.dumps(sent["body"])
    assert sent["url"].startswith("https://")
    assert "0244123456" not in payload and "admin@help.org" not in payload      # cleaned
    assert "Help Trust" not in payload and "Help Trust Admin" not in payload    # no organization or person names
    assert "## Leave" in payload                                                # guide extracts only
    assert "Organization Administrator" in payload                              # the role, for role-aware answers
    assert any(l["label"] == "Request leave" for l in data["links"])            # links still built here


def test_ai_service_down_falls_back_to_the_guide(client, org, app, monkeypatch):
    def boom(req, timeout):
        raise urllib.error.URLError("down")
    monkeypatch.setattr(assistant.urllib.request, "urlopen", boom)
    app.config["HELP_AI_API_KEY"] = "sk-test"
    try:
        login(client, "admin@help.org")
        data = ask(client, f"/o/{org.slug}/assistant/ask", "how do I request leave").get_json()
    finally:
        app.config["HELP_AI_API_KEY"] = None
    assert data["source"] == "guide" and "could not answer just now" in data["answer"]


def test_sign_in_required_and_widget_on_signed_in_pages_only(client, org):
    r = client.post("/assistant/ask", json={"question": "help"})
    assert r.status_code in (302, 401)
    assert r.status_code != 200
    assert client.post(f"/o/{org.slug}/assistant/ask", json={"question": "help"}).status_code != 200
    assert "data-assistant" not in client.get("/auth/login").get_data(as_text=True)
    login(client, "admin@help.org")
    page = client.get(f"/o/{org.slug}/").get_data(as_text=True)
    assert "data-assistant" in page and f'data-ask-url="/o/{org.slug}/assistant/ask"' in page
    assert "js/assistant.js" in page
    assert client.post(f"/o/{org.slug}/assistant/ask", json={"question": ""}).status_code == 400


def test_platform_staff_get_console_links(client, db):
    make_staff("kay@platform.org")
    login(client, "kay@platform.org")
    data = ask(client, "/assistant/ask", "How do I approve an organization on the platform?").get_json()
    assert any(l["url"] == "/platform/organizations" for l in data["links"])
