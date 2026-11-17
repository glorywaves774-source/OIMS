"""Video calls in meetings, the automatic notes maker and staff profile photos."""
import base64
import io
import json

import pytest
from PIL import Image

from app.models import Meeting, StaffProfile
from tests.conftest import login, logout, make_org, make_staff_profile
from tests.test_office import org, url  # noqa: F401  (fixture)


def _new_meeting(client, o, participants, video=True, link=""):
    data = {"title": "Board meeting", "starts_at": "2026-12-03T10:00", "participants": participants,
            "agenda": "1. Budget\n2. Recruitment", "online_link": link}
    if video:
        data["video_call"] = "y"
    r = client.post(url(o, "/meetings/new"), data=data)
    assert r.status_code == 302, r.data[:500]
    return Meeting.query.order_by(Meeting.id.desc()).first()


# --- Video calls ---------------------------------------------------------------------------------

def test_meeting_gets_an_unguessable_video_room(client, org, db):
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    assert m.video_room.startswith("ZentavaOIMS") and len(m.video_room) == 35
    room = m.video_room
    html = client.get(url(o, f"/meetings/{m.id}")).data.decode()
    assert "Join video call" in html and f"/meetings/{m.id}/call" in html
    # saving again keeps the same room; unticking removes it
    client.post(url(o, f"/meetings/{m.id}/edit"), data={"title": "Board meeting", "starts_at": "2026-12-03T10:00",
                                                         "participants": [org["ama"].id], "video_call": "y"})
    assert db.session.get(Meeting, m.id).video_room == room
    client.post(url(o, f"/meetings/{m.id}/edit"), data={"title": "Board meeting", "starts_at": "2026-12-03T10:00",
                                                         "participants": [org["ama"].id]})
    assert db.session.get(Meeting, m.id).video_room is None


def test_meeting_links_must_be_secure_and_are_named(client, org):
    o = org["org"]
    login(client, "head@hope.org")
    r = client.post(url(o, "/meetings/new"), data={"title": "X", "starts_at": "2026-12-03T10:00",
                                                    "online_link": "http://zoom.us/j/123"})
    assert r.status_code == 200 and b"https://" in r.data
    m = _new_meeting(client, o, [org["ama"].id], video=False, link="https://us02web.zoom.us/j/8812345")
    html = client.get(url(o, f"/meetings/{m.id}")).data.decode()
    assert "Join on <span translate=\"no\">Zoom</span>" in html
    assert "Join video call" not in html


def test_public_jitsi_call_opens_in_its_own_tab(client, org):
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    logout(client)
    login(client, "ama@hope.org")
    r = client.get(url(o, f"/meetings/{m.id}/call"))
    assert r.status_code == 200
    html = r.data.decode()
    assert f"https://meet.jit.si/{m.video_room}#" in html
    assert "<iframe" not in html                                  # meet.jit.si only allows short embedded calls
    import re
    links = re.findall(r'href="(https://meet\.jit\.si/[^"]+)"', html)
    assert links and all("Ama%20Person" in u and "hope.org" not in u for u in links)   # name only, never the email
    assert "frame-src" not in r.headers["Content-Security-Policy"]
    assert "microphone=(self)" in r.headers["Permissions-Policy"]
    assert r.headers["Cache-Control"] == "no-store"


def test_people_outside_the_meeting_cannot_join(client, org):
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    logout(client)
    login(client, "kofi@hope.org")                               # another department, not invited
    assert client.get(url(o, f"/meetings/{m.id}/call")).status_code == 404
    other, _ = make_org("Other Org", admin_email="admin@other.org")
    logout(client)
    login(client, "admin@other.org")
    assert client.get(url(other, f"/meetings/{m.id}/call")).status_code == 404


def test_own_jitsi_server_is_shown_inside_the_page(client, org, app):
    app.config["VIDEO_JITSI_DOMAIN"] = "video.hope.org"
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    r = client.get(url(o, f"/meetings/{m.id}/call"))
    html = r.data.decode()
    assert f'<iframe class="call-frame" src="https://video.hope.org/{m.video_room}#' in html
    assert "frame-src https://video.hope.org" in r.headers["Content-Security-Policy"]
    assert 'camera=(self "https://video.hope.org")' in r.headers["Permissions-Policy"]


def _b64d(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def test_jaas_call_has_a_signed_pass(client, org, app):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    app.config.update(JAAS_APP_ID="vpaas-magic-cookie-abc", JAAS_API_KEY_ID="vpaas-magic-cookie-abc/k1",
                      JAAS_PRIVATE_KEY=pem.replace("\n", "\\n"))
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    html = client.get(url(o, f"/meetings/{m.id}/call")).data.decode()
    start = html.index(f"https://8x8.vc/vpaas-magic-cookie-abc/{m.video_room}?jwt=")
    token = html[start:].split("jwt=", 1)[1].split("#", 1)[0]
    head, body, sig = token.split(".")
    key.public_key().verify(_b64d(sig), f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    h, claims = json.loads(_b64d(head)), json.loads(_b64d(body))
    assert h == {"alg": "RS256", "kid": "vpaas-magic-cookie-abc/k1", "typ": "JWT"}
    assert claims["aud"] == "jitsi" and claims["iss"] == "chat" and claims["sub"] == "vpaas-magic-cookie-abc"
    assert claims["room"] == m.video_room and claims["exp"] > claims["nbf"]
    user = claims["context"]["user"]
    assert user["moderator"] == "true" and user["email"] == "" and user["name"] == "Head Person"
    assert claims["context"]["features"]["recording"] == "false"


# --- Automatic notes ----------------------------------------------------------------------------

TRANSCRIPT = """[10:01] Good morning everyone, thank you for coming.
[10:02] The budget for the school kits is now 45,000 cedis after the supplier changed prices.
[10:04] We agreed to move the community meeting to the 14th of December.
[10:05] Ama will send the revised budget to the donor by Friday.
[10:06] Call me on 024 123 4567 or write to kwame@example.org if anything changes.
[10:07] Is the new warehouse ready?
[10:08] Okay."""


def test_notes_are_kept_and_only_managers_take_them(client, org):
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    r = client.post(url(o, f"/meetings/{m.id}/notes"), json={"transcript": "[10:00] Opening."})
    assert r.get_json() == {"saved": True}
    html = client.get(url(o, f"/meetings/{m.id}")).data.decode()
    assert "Live notes" in html and "[10:00] Opening." in html
    logout(client)
    login(client, "ama@hope.org")
    assert client.post(url(o, f"/meetings/{m.id}/notes"), json={"transcript": "x"}).status_code == 403
    assert client.post(url(o, f"/meetings/{m.id}/notes/draft"), json={"transcript": "x"}).status_code == 403
    assert "Live notes" not in client.get(url(o, f"/meetings/{m.id}")).data.decode()


def test_draft_minutes_without_ai(client, org, app):
    app.config["HELP_AI_API_KEY"] = None
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    r = client.post(url(o, f"/meetings/{m.id}/notes/draft"), json={"transcript": TRANSCRIPT})
    data = r.get_json()
    assert data["source"] == "rules"
    d = data["draft"]
    assert "Minutes (draft) — Board meeting" in d
    assert "Decisions:\n- We agreed to move the community meeting to the 14th of December." in d
    assert "- Ama will send the revised budget to the donor by Friday." in d.split("Action points:")[1]
    assert "Open questions:\n- Is the new warehouse ready?" in d
    assert "- 1. Budget" in d or "- Budget" in d
    assert "Okay." not in d
    assert db_transcript(m) == TRANSCRIPT
    assert client.post(url(o, f"/meetings/{m.id}/notes/draft"), json={"transcript": "  "}).status_code == 400


def db_transcript(m):
    from app.extensions import db
    db.session.expire_all()
    return db.session.get(Meeting, m.id).transcript


def test_draft_minutes_in_french(client, org, app):
    app.config["HELP_AI_API_KEY"] = None
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    client.post("/language", data={"lang": "fr", "next": "/"})
    d = client.post(url(o, f"/meetings/{m.id}/notes/draft"),
                    json={"transcript": "Il a été convenu de reporter la réunion. Ama va envoyer le budget d'ici vendredi."}
                    ).get_json()["draft"]
    assert "Compte rendu (brouillon)" in d and "Décisions:\n- Il a été convenu" in d
    assert "Actions à mener:\n- Ama va envoyer le budget" in d


def test_ai_draft_gets_only_redacted_transcript(client, org, app, monkeypatch):
    app.config["HELP_AI_API_KEY"] = "test-key"
    sent = {}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=0):
        sent["body"] = json.loads(req.data.decode())
        sent["url"] = req.full_url
        return Reply(json.dumps({"content": [{"type": "text", "text": "Summary of discussion:\n- Budget."}]}).encode())

    monkeypatch.setattr("app.notes.urllib.request.urlopen", fake_urlopen)
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    data = client.post(url(o, f"/meetings/{m.id}/notes/draft"), json={"transcript": TRANSCRIPT}).get_json()
    assert data["source"] == "ai" and "Summary of discussion:\n- Budget." in data["draft"]
    content = sent["body"]["messages"][0]["content"]
    assert "024 123 4567" not in content and "kwame@example.org" not in content
    assert "[email]" in content and "[number]" in content
    assert "head@hope.org" not in json.dumps(sent["body"])
    assert sent["url"].startswith("https://")


def test_ai_failure_falls_back_to_built_in_draft(client, org, app, monkeypatch):
    app.config["HELP_AI_API_KEY"] = "test-key"

    def broken(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr("app.notes.urllib.request.urlopen", broken)
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    assert client.post(url(o, f"/meetings/{m.id}/notes/draft"), json={"transcript": TRANSCRIPT}).get_json()["source"] == "rules"


# --- Staff photos -------------------------------------------------------------------------------

def _image(fmt="PNG", size=(900, 600), exif=None):
    buf = io.BytesIO()
    img = Image.new("RGB", size, (30, 120, 200))
    if exif is not None:
        img.save(buf, fmt, exif=exif)
    else:
        img.save(buf, fmt)
    buf.seek(0)
    return buf


def test_hr_sets_a_staff_photo_and_it_is_cleaned(client, org, db):
    o = org["org"]
    ama = org["ama_staff"]
    ex = Image.Exif()
    ex[0x010F] = "SecretCameraMaker"
    login(client, "hr@hope.org")
    r = client.post(url(o, f"/staff/{ama.id}/photo"), data={"photo": (_image("JPEG", exif=ex), "me.jpg")},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    db.session.expire_all()
    s = db.session.get(StaffProfile, ama.id)
    img = Image.open(io.BytesIO(s.photo_data))
    assert img.format == "JPEG" and img.size == (700, 900)
    assert b"SecretCameraMaker" not in s.photo_data
    r = client.get(url(o, f"/staff/{ama.id}/photo"))
    assert r.status_code == 200 and r.mimetype == "image/jpeg" and "private" in r.headers["Cache-Control"]
    assert client.get(url(o, f"/staff/{ama.id}/photo"), headers={"If-None-Match": r.headers["ETag"]}).status_code == 304
    listing = client.get(url(o, "/staff/")).data.decode()
    assert f"/staff/{ama.id}/photo?v=" in listing
    detail = client.get(url(o, f"/staff/{ama.id}"))
    assert "camera=(self)" in detail.headers["Permissions-Policy"] and "Take photo" in detail.data.decode()
    client.post(url(o, f"/staff/{ama.id}/photo/delete"))
    db.session.expire_all()
    assert db.session.get(StaffProfile, ama.id).photo_updated_at is None


def test_people_set_their_own_photo_only(client, org, db):
    o = org["org"]
    login(client, "ama@hope.org")
    own = client.post(url(o, f"/staff/{org['ama_staff'].id}/photo"), data={"photo": (_image(), "me.png")},
                      content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert own.get_json() == {"saved": True}
    other = client.post(url(o, f"/staff/{org['kofi_staff'].id}/photo"), data={"photo": (_image(), "x.png")},
                        content_type="multipart/form-data")
    assert other.status_code == 403
    assert "Take photo" not in client.get(url(o, f"/staff/{org['kofi_staff'].id}")).data.decode()


def test_not_a_photo_is_refused(client, org):
    o = org["org"]
    login(client, "hr@hope.org")
    r = client.post(url(o, f"/staff/{org['ama_staff'].id}/photo"),
                    data={"photo": (io.BytesIO(b"%PDF-1.7 not an image"), "cv.pdf")},
                    content_type="multipart/form-data", headers={"Accept": "application/json"})
    assert r.status_code == 400 and "photo" in r.get_json()["error"]


def test_photos_stay_inside_their_organization(client, org, db):
    o = org["org"]
    login(client, "hr@hope.org")
    client.post(url(o, f"/staff/{org['ama_staff'].id}/photo"), data={"photo": (_image(), "me.png")},
                content_type="multipart/form-data")
    logout(client)
    other, _ = make_org("Other Org", admin_email="admin@other.org")
    login(client, "admin@other.org")
    assert client.get(url(other, f"/staff/{org['ama_staff'].id}/photo")).status_code == 404
    assert client.get(url(o, f"/staff/{org['ama_staff'].id}/photo")).status_code in (403, 404)


@pytest.mark.parametrize("fmt", ["PNG", "WEBP", "JPEG"])
def test_photo_formats(fmt):
    from app.photos import make_profile_photo
    out = make_profile_photo(_image(fmt, size=(300, 1200)).getvalue())
    assert Image.open(io.BytesIO(out)).size == (700, 900)


# --- Attachments sent exactly as the real form sends them (no "who can see it" field) --------------

def test_meeting_attachment_upload_from_the_real_form(client, org, db):
    from app.models import Document
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    page = client.get(url(o, f"/documents/upload?related_type=meeting&related_id={m.id}")).data.decode()
    assert 'name="visibility"' not in page and f"/meetings/{m.id}" in page          # Cancel goes back to the meeting
    r = client.post(url(o, f"/documents/upload?related_type=meeting&related_id={m.id}"),
                    data={"related_type": "meeting", "related_id": m.id, "title": "Agenda pack",
                          "file": (io.BytesIO(b"%PDF-1.4\n%%EOF\n"), "agenda.pdf")},
                    content_type="multipart/form-data")
    assert r.status_code == 302 and f"/meetings/{m.id}" in r.headers["Location"]
    doc = Document.query.filter_by(related_type="meeting", related_id=m.id).one()
    assert doc.visibility == "restricted" and doc.status == "approved"
    assert "Agenda pack" in client.get(url(o, f"/meetings/{m.id}")).data.decode()
    # a participant can attach too
    logout(client)
    login(client, "ama@hope.org")
    r = client.post(url(o, f"/documents/upload?related_type=meeting&related_id={m.id}"),
                    data={"related_type": "meeting", "related_id": m.id, "title": "My notes",
                          "file": (io.BytesIO(b"a,b\n1,2\n"), "notes.csv")},
                    content_type="multipart/form-data")
    assert r.status_code == 302


def test_upload_errors_are_shown(client, org):
    o = org["org"]
    login(client, "head@hope.org")
    m = _new_meeting(client, o, [org["ama"].id])
    r = client.post(url(o, f"/documents/upload?related_type=meeting&related_id={m.id}"),
                    data={"related_type": "meeting", "related_id": m.id, "title": ""},
                    content_type="multipart/form-data")
    assert r.status_code == 200 and b"invalid-feedback" in r.data


def test_photo_from_phone_camera_input_and_passport_sheet(client, org, db):
    o = org["org"]
    ama = org["ama_staff"]
    login(client, "hr@hope.org")
    page = client.get(url(o, f"/staff/{ama.id}")).data.decode()
    assert 'capture="user"' in page and 'capture="environment"' in page
    assert "Front camera" in page and "Back camera" in page
    # the form has three picture inputs (gallery, front, back); only the chosen one carries a file
    r = client.post(url(o, f"/staff/{ama.id}/photo"),
                    data={"photo": [(io.BytesIO(b""), ""), (_image("JPEG", size=(1080, 1920)), "IMG_0001.jpg")]},
                    content_type="multipart/form-data")
    assert r.status_code == 302
    db.session.expire_all()
    assert Image.open(io.BytesIO(db.session.get(StaffProfile, ama.id).photo_data)).size == (700, 900)
    sheet = client.get(url(o, f"/staff/{ama.id}/photo/print?copies=4&name=1")).data.decode()
    assert sheet.count(f"/staff/{ama.id}/photo?v=") == 4 and "35 × 45 mm" in sheet
    assert "Print passport photos" in client.get(url(o, f"/staff/{ama.id}")).data.decode()
