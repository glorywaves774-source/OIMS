"""ZENTAVA Assistant endpoints: one inside each workspace (links for that workspace and role), one for the
Kayron console and account pages. Signed-in only, CSRF-protected (X-CSRFToken header), rate limited."""
from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from app.assistant import answer
from app.blueprints.tenant import workspace_blueprint
from app.extensions import limiter
from app.i18n import current_language


def _user_key():
    return f"user:{current_user.get_id()}" if current_user.is_authenticated else request.remote_addr


def _ask():
    q = (request.get_json(silent=True) or {}).get("question") or request.form.get("question") or ""
    if not q.strip():
        abort(400)
    return jsonify(answer(q, current_language()))


bp = workspace_blueprint("assistant", __name__, "/assistant")


@bp.route("/ask", methods=["POST"])
@limiter.limit("12 per minute; 200 per day", key_func=_user_key)
def ask():
    return _ask()


global_bp = Blueprint("assistant_global", __name__)


@global_bp.route("/assistant/ask", methods=["POST"])
@login_required
@limiter.limit("12 per minute; 200 per day", key_func=_user_key)
def ask_global():
    return _ask()
