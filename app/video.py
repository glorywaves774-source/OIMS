"""Video calls for meetings, using Jitsi.

Three ways to run, chosen by settings (environment variables only):
- JaaS (8x8's hosted Jitsi; JAAS_APP_ID, JAAS_API_KEY_ID, JAAS_PRIVATE_KEY): the call opens inside the meeting page,
  with a signed pass that names the person and makes the organizer a moderator.
- Your own Jitsi server (VIDEO_JITSI_DOMAIN): the call opens inside the meeting page.
- Neither (default): the free public meet.jit.si server. It only allows short calls inside another site, so the call
  opens in its own tab (the notes stay on the ZENTAVA page).

Only the person's display name goes to the video service, never their email address. Rooms have long random names,
so nobody can guess them."""
import base64
import json
import secrets
import string
import time
from urllib.parse import quote, urlparse

from flask import current_app

PUBLIC_JITSI = "meet.jit.si"
JAAS_DOMAIN = "8x8.vc"
_ALPHABET = string.ascii_letters + string.digits

KNOWN_LINKS = (
    ("meet.google.com", "Google Meet"),
    ("zoom.us", "Zoom"),
    ("zoom.com", "Zoom"),
    ("teams.microsoft.com", "Microsoft Teams"),
    ("teams.live.com", "Microsoft Teams"),
    ("webex.com", "Webex"),
    ("whereby.com", "Whereby"),
    ("meet.jit.si", "Jitsi Meet"),
)


def enabled():
    return bool(current_app.config.get("VIDEO_CALLS", True))


def new_room():
    return "ZentavaOIMS" + "".join(secrets.choice(_ALPHABET) for _ in range(24))


def _jaas_ready(cfg):
    return all(cfg.get(k) for k in ("JAAS_APP_ID", "JAAS_API_KEY_ID", "JAAS_PRIVATE_KEY"))


def mode():
    """'jaas' or 'own' (shown inside the page) or 'public' (opens in its own tab)."""
    cfg = current_app.config
    if _jaas_ready(cfg):
        return "jaas"
    if (cfg.get("VIDEO_JITSI_DOMAIN") or PUBLIC_JITSI) != PUBLIC_JITSI:
        return "own"
    return "public"


def embedded():
    return mode() in ("jaas", "own")


def domain():
    return JAAS_DOMAIN if mode() == "jaas" else (current_app.config.get("VIDEO_JITSI_DOMAIN") or PUBLIC_JITSI)


def origin():
    return f"https://{domain()}"


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jaas_token(room, user_id, name, moderator, hours=4):
    """A short-lived pass for one room, signed with the JaaS private key (RS256)."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    cfg = current_app.config
    now = int(time.time())
    header = {"alg": "RS256", "kid": cfg["JAAS_API_KEY_ID"], "typ": "JWT"}
    payload = {
        "aud": "jitsi", "iss": "chat", "sub": cfg["JAAS_APP_ID"], "room": room,
        "iat": now, "nbf": now - 60, "exp": now + hours * 3600,
        "context": {
            "user": {"id": str(user_id), "name": name, "avatar": "", "email": "",
                     "moderator": "true" if moderator else "false"},
            "features": {"livestreaming": "false", "recording": "false", "transcription": "false",
                         "outbound-call": "false", "sip-outbound-call": "false"},
        },
    }
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}." \
                    f"{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    pem = cfg["JAAS_PRIVATE_KEY"].replace("\\n", "\n").encode()
    key = serialization.load_pem_private_key(pem, password=None)
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{_b64(signature)}"


def _hash_config(name, lang):
    opts = {
        "config.prejoinConfig.enabled": True,
        "config.disableDeepLinking": True,       # phones: stay in the browser instead of asking for the app
        "config.defaultLanguage": lang,
        "userInfo.displayName": name,
    }
    return "#" + "&".join(f"{k}={quote(json.dumps(v))}" for k, v in opts.items())


def join_url(room, user_id, name, moderator, lang="en"):
    if mode() == "jaas":
        app_id = current_app.config["JAAS_APP_ID"]
        token = jaas_token(room, user_id, name, moderator)
        return f"https://{JAAS_DOMAIN}/{app_id}/{room}?jwt={token}" + _hash_config(name, lang)
    return f"https://{domain()}/{room}" + _hash_config(name, lang)


def link_label(url):
    """'Google Meet', 'Zoom', ... for a pasted meeting link; None when it is not one we recognise."""
    host = (urlparse(url or "").hostname or "").lower()
    for known, label in KNOWN_LINKS:
        if host == known or host.endswith("." + known):
            return label
    return None
