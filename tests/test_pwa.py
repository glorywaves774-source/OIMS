"""Installable app: manifest, icons, service worker, offline page and install buttons."""
import json
import os
import re

from PIL import Image

from tests.conftest import add_member, login, make_org, make_user

STATIC = os.path.join(os.path.dirname(__file__), "..", "app", "static")


def test_manifest_meets_install_requirements(client):
    r = client.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.mimetype == "application/manifest+json"
    m = json.loads(r.data)
    assert m["name"] == "ZENTAVA OIMS" and m["short_name"] == "ZENTAVA"
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["scope"] == "/"
    sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    assert m["theme_color"].startswith("#") and m["background_color"].startswith("#")


def test_every_manifest_icon_exists_at_its_stated_size(client):
    m = json.loads(client.get("/manifest.webmanifest").data)
    for icon in m["icons"]:
        r = client.get(icon["src"])
        assert r.status_code == 200, icon["src"]
        if icon["type"] == "image/png":
            w, h = (int(x) for x in icon["sizes"].split("x"))
            path = os.path.join(STATIC, icon["src"].split("/static/", 1)[1])
            assert Image.open(path).size == (w, h)
    apple = Image.open(os.path.join(STATIC, "img", "apple-touch-icon.png"))
    assert apple.size == (180, 180) and apple.mode == "RGB"   # iOS shows transparent corners as black


def test_service_worker_is_served_fresh_and_keeps_only_public_files(client, app):
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.mimetype == "application/javascript"
    assert r.headers["Cache-Control"] == "no-cache"
    body = r.get_data(as_text=True)
    assert app.config["OIMS_VERSION"] in body               # each release replaces the old cache
    kept = json.loads(re.search(r"var ASSETS = (\[.*?\]);", body).group(1))
    assert kept and all(u.startswith("/static/") for u in kept)
    assert '"/offline"' in body
    assert 'req.method !== "GET"' in body                    # forms and uploads never pass through it


def test_offline_page_is_public_and_holds_nothing_personal(client, db):
    org, _ = make_org("Agri She")
    user = make_user("ama@agri.example", name="Ama Owusu")
    add_member(org, user.email)
    login(client, user.email)
    r = client.get("/offline")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "You are offline" in html
    assert "Ama Owusu" not in html and "ama@agri.example" not in html and "csrf" not in html.lower()


def test_offline_page_is_not_swallowed_by_forced_password_change(client, db):
    user = make_user("new@agri.example")
    user.must_change_password = True
    db.session.commit()
    login(client, user.email)
    assert client.get("/offline").status_code == 200
    assert client.get("/sw.js").status_code == 200


def test_pages_link_the_manifest_and_offer_install(client):
    html = client.get("/auth/login").get_data(as_text=True)
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'name="theme-color"' in html
    assert "js/pwa.js" in html
    assert "data-install hidden" in html                   # shown only when the device can install
    assert 'id="install-ios-modal"' in html


def test_install_text_in_french(client):
    client.post("/language", data={"lang": "fr", "next": "/auth/login"})
    html = client.get("/auth/login").get_data(as_text=True)
    assert "Installer sur iPhone ou iPad" in html
    assert "Touchez le bouton Partager" in html
    assert "Vous êtes hors ligne" in client.get("/offline").get_data(as_text=True)


def test_csp_still_strict(client):
    csp = client.get("/auth/login").headers["Content-Security-Policy"]
    assert "script-src 'self';" in csp and "unsafe-inline" not in csp
