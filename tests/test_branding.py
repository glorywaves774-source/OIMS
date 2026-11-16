"""ZENTAVA OIMS branding: name, tagline, logo and acronym appear where people see them."""
from app import twofactor


def test_public_page_shows_brand(client):
    html = client.get("/").get_data(as_text=True)
    assert '<span class="wm-brand">ZENTAVA</span> <span class="wm-product">OIMS</span>' in html
    assert "Organized. Transparent. Accountable." in html
    assert "img/logo.svg" in html
    for word in ("Zonal", "Enterprise", "Network for", "Transparent", "Administration,", "Visibility and", "Accountability"):
        assert word in html


def test_sign_in_page_shows_brand(client):
    html = client.get("/auth/login").get_data(as_text=True)
    assert "wm-brand" in html and "img/logo.svg" in html and "<title>Sign in · ZENTAVA OIMS</title>" in html


def test_logo_and_favicon_are_served(client):
    for path in ("/static/img/logo.svg", "/static/img/favicon.svg"):
        r = client.get(path)
        assert r.status_code == 200 and b"#f2b134" in r.data and b"#0f9d8a" in r.data


def test_authenticator_label_is_zentava():
    assert twofactor.ISSUER == "ZENTAVA OIMS"
