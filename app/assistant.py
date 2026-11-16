"""ZENTAVA Assistant: answers "how do I…" questions from the help guide (app/help/guide.<lang>.md).

Privacy and safety
* Only the guide is used as knowledge. No records (people, money, documents) are ever sent anywhere.
* Before a question leaves the server, phone numbers, email addresses and ID / account numbers are removed.
  The person's name and email are never sent; only their role and permission codes are.
* Links are built here, from the guide, and only for pages the person's role can open. The AI service
  cannot add links: it only phrases the answer.
* Without an AI key (HELP_AI_API_KEY or ANTHROPIC_API_KEY) the assistant answers straight from the guide.
"""
import json
import logging
import os
import re
import unicodedata
import urllib.error
import urllib.request
from functools import lru_cache

from flask import current_app, g, url_for
from flask_login import current_user

log = logging.getLogger(__name__)
GUIDE_DIR = os.path.join(os.path.dirname(__file__), "help")
LANG_NAMES = {"en": "English", "fr": "French"}
STOP = set("""a an the and or of to in on for is are be do does how can i my me we you your it this that what where when who
with from at as by about please which there have has get make add see find use need want
le la les un une des du de et ou en au aux pour est sont je mon ma mes nous vous votre comment puis peut quoi
où quand qui avec dans sur par il elle ce cette ça faire voir trouver ajouter""".split())

MESSAGES = {
    "en": {"none": "I could not find that in the help guide. Try other words, or ask your organization "
                   "administrator.",
           "who": "Who does this: {who}.",
           "error": "The assistant could not answer just now; here is what the help guide says."},
    "fr": {"none": "Je n'ai pas trouvé cela dans le guide d'aide. Essayez d'autres mots, ou demandez à "
                   "l'administrateur de votre organisation.",
           "who": "Qui s'en occupe : {who}.",
           "error": "L'assistant n'a pas pu répondre pour l'instant ; voici ce que dit le guide d'aide."},
}


# --- the guide ---------------------------------------------------------------------------------

def _norm(text):
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", _norm(text)) if len(w) > 1 and w not in STOP]


def _stem(w):
    return w[:5] if len(w) > 5 else w


@lru_cache(maxsize=4)
def _load(lang, mtime):
    path = os.path.join(GUIDE_DIR, f"guide.{lang}.md")
    text = re.sub(r"<!--.*?-->", "", open(path, encoding="utf-8").read(), flags=re.S)
    sections = []
    for block in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = block.strip().split("\n")
        sec = {"title": lines[0].strip(), "keywords": "", "links": [], "who": "", "body": []}
        for line in lines[1:]:
            if line.startswith("keywords:"):
                sec["keywords"] = line[9:].strip()
            elif line.startswith("links:"):
                for part in line[6:].split(";"):
                    m = re.match(r"\s*(.+?)\s*=\s*([\w.]+)\s*(?:\[([\w.]+)\])?\s*$", part)
                    if m:
                        sec["links"].append((m.group(1), m.group(2), m.group(3)))
            elif line.startswith("who:"):
                sec["who"] = line[4:].strip()
            elif line.strip():
                sec["body"].append(line.strip())
        sec["body"] = " ".join(sec["body"])
        sec["kw"] = {_stem(t) for t in _tokens(sec["keywords"])}
        sec["tt"] = {_stem(t) for t in _tokens(sec["title"])}
        sec["bt"] = {_stem(t) for t in _tokens(sec["body"])}
        sections.append(sec)
    return sections


def guide(lang):
    lang = lang if lang in LANG_NAMES else "en"
    path = os.path.join(GUIDE_DIR, f"guide.{lang}.md")
    return _load(lang, os.path.getmtime(path))


def search(question, lang, k=3):
    """Guide sections that best match the question (keywords count most, then title, then text)."""
    q = {_stem(t) for t in _tokens(question)}
    scored = []
    for i, s in enumerate(guide(lang)):
        score = 3 * len(q & s["kw"]) + 2 * len(q & s["tt"]) + len(q & s["bt"])
        if score:
            scored.append((score, -i, s))
    scored.sort(reverse=True)
    if not scored:
        return []
    best = scored[0][0]
    # other sections only when nearly as relevant as the best one (so a leave question gets leave links)
    return [s for score, _, s in scored[:k] if score >= max(2, best * 0.75)] or [scored[0][2]]


# --- links the person may open ------------------------------------------------------------------

def _may(perm):
    if perm is None:
        return True
    if perm == "platform":
        return bool(getattr(current_user, "is_platform_staff", False))
    if g.get("tenant") is None:
        return False
    from app.rbac import can
    return can(perm)


def links_for(sections, limit=6):
    out, seen = [], set()
    for s in sections:
        for label, endpoint, perm in s["links"]:
            if endpoint in seen or not _may(perm):
                continue
            needs_workspace = any("org_slug" in r.arguments
                                  for r in current_app.url_map.iter_rules(endpoint))
            if needs_workspace and g.get("tenant") is None:
                continue   # a workspace page, asked from outside a workspace
            try:
                url = url_for(endpoint, org_slug=g.tenant.slug) if needs_workspace else url_for(endpoint)
            except Exception:  # noqa: BLE001 - a page that does not apply here is simply not offered
                continue
            seen.add(endpoint)
            out.append({"label": label, "url": url})
            if len(out) >= limit:
                return out
    return out


# --- privacy -------------------------------------------------------------------------------------

REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"\bGHA-?\d{9}-?\d\b", re.I), "[ID number]"),
    (re.compile(r"(?<![\w/])\+?\d[\d\s().-]{6,}\d"), "[number]"),
    (re.compile(r"\b(?=[A-Z0-9-]*\d{5,})[A-Z0-9][A-Z0-9-]{5,}\b"), "[number]"),
]


def redact(text):
    for rx, repl in REDACTIONS:
        text = rx.sub(repl, text)
    return text


# --- answering -----------------------------------------------------------------------------------

def _api_key():
    cfg = current_app.config
    return cfg.get("HELP_AI_API_KEY") or cfg.get("ANTHROPIC_API_KEY")


def _role_line():
    if getattr(current_user, "is_platform_staff", False) and g.get("tenant") is None:
        return "Kayron platform staff", []
    m = g.get("membership")
    role = m.role.name if m is not None and m.role is not None else "member"
    from app.rbac import effective_permissions
    try:
        perms = sorted(effective_permissions())
    except Exception:  # noqa: BLE001
        perms = []
    return role, perms


def _ai_answer(question, sections, lang):
    role, perms = _role_line()
    extracts = "\n\n".join(f"## {s['title']}\nWho: {s['who']}\n{s['body']}" for s in sections)
    system = (
        "You are ZENTAVA Assistant, the help assistant of ZENTAVA OIMS, an organization management system. "
        "Answer ONLY from the help guide extracts given. If they do not answer the question, say you could not "
        "find it in the help guide. Do not invent features, menus, links or steps. "
        f"Reply in {LANG_NAMES.get(lang, 'English')}, in plain words, at most 120 words, without markdown "
        "headings, tables or links (links are shown separately). "
        f"The person's role is '{role}'. Their permission codes: {', '.join(perms) or 'none listed'}. "
        "If the task needs a permission they do not have, say plainly that it is another role's job, naming "
        "the role from the 'Who' line, and suggest asking that person.")
    body = json.dumps({
        "model": current_app.config.get("HELP_AI_MODEL", "claude-haiku-5-5"),
        "max_tokens": 400,
        "system": system,
        "messages": [{"role": "user", "content": f"Help guide extracts:\n\n{extracts}\n\nQuestion: {question}"}],
    }).encode()
    url = current_app.config.get("HELP_AI_URL", "https://api.anthropic.com/v1/messages")
    if not url.startswith("https://"):
        raise RuntimeError("HELP_AI_URL must start with https://")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "x-api-key": _api_key(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode())
    text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text").strip()
    if not text:
        raise RuntimeError("empty answer")
    return text


def answer(question, lang):
    """{answer, links, source}: 'ai' (phrased by the AI service) or 'guide' (straight from the guide)."""
    lang = lang if lang in LANG_NAMES else "en"
    question = (question or "").strip()[:500]
    msg = MESSAGES[lang]
    sections = search(question, lang)
    if not sections:
        return {"answer": msg["none"], "links": [], "source": "guide"}
    links = links_for(sections)
    if _api_key():
        try:
            return {"answer": _ai_answer(redact(question), sections, lang), "links": links, "source": "ai"}
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError, KeyError) as exc:
            log.warning("Help assistant: AI service unavailable (%s); answering from the guide", exc)
            prefix = msg["error"] + "\n\n"
    else:
        prefix = ""
    top = sections[0]
    text = prefix + top["body"] + ("\n\n" + msg["who"].format(who=top["who"]) if top["who"] else "")
    return {"answer": text, "links": links, "source": "guide", "title": top["title"]}
