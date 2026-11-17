"""Installable app: the web app manifest, the service worker and the offline page.

Privacy rule: the service worker only keeps the public look of the app (styles, scripts, icons, fonts
and the offline page). It never stores pages, records, downloads or anything sent to the server, so
nothing private stays on a phone or shared computer after signing out."""
import json

from flask import Blueprint, Response, current_app, render_template, url_for

bp = Blueprint("pwa", __name__)

THEME_LIGHT = "#14213d"      # ZENTAVA navy: the installed app's title bar
BACKGROUND = "#f4f6f8"       # splash screen behind the icon while the app opens


def static_assets():
    """Files the offline page needs, kept so it shows properly without a connection."""
    files = ("vendor/bootstrap/bootstrap.min.css", "vendor/bootstrap-icons/bootstrap-icons.min.css",
             "css/app.css", "css/dark.css", "css/mobile.css", "js/theme-init.js", "js/pwa.js",
             "img/logo.svg", "img/favicon.svg", "img/icon-192.png")
    return [url_for("static", filename=f) for f in files]


@bp.route("/manifest.webmanifest")
def manifest():
    cfg = current_app.config
    icon = lambda f: url_for("static", filename=f"img/{f}")  # noqa: E731
    data = {
        "id": "/",
        "name": cfg["APP_NAME"],
        "short_name": cfg["BRAND_NAME"],
        "description": f"{cfg['APP_FULL_NAME']} Provided by {cfg['PLATFORM_OWNER']}.",
        "lang": "en",
        "dir": "ltr",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui"],
        "orientation": "any",
        "theme_color": THEME_LIGHT,
        "background_color": BACKGROUND,
        "categories": ["business", "productivity"],
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": icon("icon-maskable-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "maskable"},
            {"src": icon("icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": icon("logo.svg"), "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        ],
    }
    resp = Response(json.dumps(data, indent=1), mimetype="application/manifest+json")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@bp.route("/sw.js")
def service_worker():
    body = render_template("pwa/sw.js", version=current_app.config["OIMS_VERSION"],
                           assets=static_assets(), offline=url_for("pwa.offline"))
    resp = Response(body, mimetype="application/javascript")
    # Always ask the server for the newest worker, so each release takes over promptly.
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


@bp.route("/offline")
def offline():
    """Shown by the installed app when there is no connection. Holds no personal information."""
    resp = Response(render_template("pwa/offline.html"))
    resp.headers["Cache-Control"] = "no-cache"
    return resp
