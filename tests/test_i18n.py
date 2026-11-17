"""French: the switch, translated pages, and typed-in data left alone."""
import json
import os
import re

from app.i18n import translate_html, translate_text
from tests.conftest import login, make_org


def test_switch_for_visitors_and_users(client, db):
    page = client.get("/auth/login").get_data(as_text=True)
    assert 'lang="en"' in page and "lang-btn" in page and "Sign in" in page
    r = client.post("/language", data={"lang": "fr", "next": "/auth/login"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/auth/login")
    assert "lang=fr" in r.headers["Set-Cookie"]
    page = client.get("/auth/login").get_data(as_text=True)
    assert 'lang="fr"' in page and "Se connecter" in page and "Mot de passe oublié ?" in page
    # a signed-in person keeps the choice on their account
    org, admin = make_org("Langue Trust", admin_email="admin@langue.org")
    login(client, "admin@langue.org")
    client.post("/language", data={"lang": "fr", "next": f"/o/{org.slug}/"})
    from app.models import User
    assert User.query.filter_by(email="admin@langue.org").one().language == "fr"
    client.delete_cookie("lang")
    page = client.get(f"/o/{org.slug}/").get_data(as_text=True)
    assert "Tableau de bord" in page
    # the organization's name is typed-in data and stays as written
    assert "Langue Trust" in page
    # back to English
    client.post("/language", data={"lang": "en", "next": f"/o/{org.slug}/"})
    assert "Dashboard" in client.get(f"/o/{org.slug}/").get_data(as_text=True)


def test_switch_refuses_odd_input(client):
    assert client.post("/language", data={"lang": "de"}).status_code == 400
    r = client.post("/language", data={"lang": "fr", "next": "//evil.example"})
    assert r.headers["Location"].endswith("/")      # off-site return address ignored


def test_typed_in_data_is_never_translated(app):
    with app.app_context():
        html = ('<p>Sign in</p><span translate="no">Sign in</span><option value="7">Finance</option>'
                '<option value="">— Choose —</option><script>var a = "Sign in";</script><textarea placeholder="Ask a question…">Sign in</textarea>'
                '<input type="text" value="Sign in"><input type="submit" value="Save">'
                '<a title="Edit" data-confirm="Cancel this meeting and notify everyone?">x</a>')
        out = translate_html(html, "fr")
    assert "<p>Se connecter</p>" in out
    assert '<span translate="no">Sign in</span>' in out          # marked as typed in
    assert '<option value="7">Finance</option>' in out            # a record chosen from a list
    assert "— Choisir —" in out                                    # the list's own prompt
    assert 'var a = "Sign in";' in out and 'placeholder="Posez une question…">Sign in</textarea>' in out
    assert 'value="Sign in"' in out and 'value="Enregistrer"' in out   # field content kept; button label translated
    assert 'title="Modifier"' in out and "Annuler cette réunion" in out


def test_patterns_dates_and_numbers(app):
    with app.app_context():
        assert translate_text("Remove Yaw Darko from the team?", "fr") == "Retirer Yaw Darko de l'équipe ?"
        assert translate_text("78 of 200", "fr") == "78 sur 200"
        assert translate_text("Board of directors", "fr") == "Board of directors"   # number-only pattern
        assert translate_text("Wednesday 18 November", "fr") == "mercredi 18 novembre"
        assert translate_text("Activities · PRJ/2026/001 · ZENTAVA OIMS", "fr") == \
            "Activités · PRJ/2026/001 · ZENTAVA OIMS"
        assert translate_text("Something nobody wrote", "fr") == "Something nobody wrote"   # never guessed
        assert translate_text("  Sign in \n", "fr") == "  Se connecter \n"              # spacing kept
        assert translate_text("· Department Head ·", "fr") == "· Chef de département ·"   # between separators


def test_dictionary_placeholders_match():
    path = os.path.join(os.path.dirname(__file__), "..", "app", "static", "i18n", "fr.json")
    data = json.load(open(path, encoding="utf-8"))
    assert len(data["strings"]) > 2000
    for src, dst in list(data["patterns"].items()) + list(data["numeric_patterns"].items()):
        assert sorted(re.findall(r"\{\d+\}", src)) == sorted(re.findall(r"\{\d+\}", dst)), src
    for src, dst in data["strings"].items():
        assert "{" not in src and dst.strip(), src


def test_language_picked_on_sign_in_page_becomes_the_persons_setting(client, db):
    from tests.conftest import add_member, login, make_org, make_user
    org, _ = make_org("Agri She")
    user = make_user("ama.lang@agri.example")
    add_member(org, user.email)
    user.language = "en"
    db.session.commit()
    client.post("/language", data={"lang": "fr", "next": "/auth/login"})
    login(client, user.email)
    db.session.refresh(user)
    assert user.language == "fr"
    assert 'lang="fr"' in client.get("/account/", follow_redirects=True).get_data(as_text=True)


def test_saved_language_kept_when_nothing_picked_before_sign_in(client, db):
    from tests.conftest import add_member, login, make_org, make_user
    org, _ = make_org("Agri She")
    user = make_user("kojo.lang@agri.example")
    add_member(org, user.email)
    user.language = "fr"
    db.session.commit()
    login(client, user.email)
    db.session.refresh(user)
    assert user.language == "fr"


def test_svg_titles_translated_but_chart_text_kept(app):
    from app.i18n import translate_html
    with app.test_request_context("/"):
        out = translate_html('<svg><title>Spent as a share of the budget</title><text>Today</text></svg>', "fr")
    assert "Part du budget dépensée" in out and "<text>Today</text>" in out


def test_error_pages_in_french(client):
    client.post("/language", data={"lang": "fr", "next": "/"})
    html = client.get("/no-such-page").get_data(as_text=True)
    assert "Page introuvable" in html and "Erreur 404" in html
    assert "Cette page n'existe pas" in html or "Cette page n&#39;existe pas" in html


def test_month_choices_translated_but_record_choices_kept(app):
    from app.i18n import translate_html
    with app.test_request_context("/"):
        out = translate_html('<select><option value="3">March</option><option value="7">Grace Open</option></select>', "fr")
    assert ">Mars<" in out and ">Grace Open<" in out
