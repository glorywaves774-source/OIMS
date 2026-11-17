"""Automatic meeting notes: turns the live transcript (or typed notes) into draft minutes.

Without an AI key the draft is built here: a short summary, the decisions, the action points and the open
questions, picked out from what was said. With HELP_AI_API_KEY set, the AI service writes the draft from the
transcript after phone numbers, email addresses and ID numbers are removed; no records from the system are sent.
The draft is only shown in the minutes box: a person reads it, corrects it and saves it."""
import json
import re
import urllib.request

from flask import current_app

from app.assistant import _api_key, redact

MAX_TRANSCRIPT = 60000

CUES = {
    "en": {
        "decision": r"\b(agreed|agree that|decided|decision|approved?|resolved|we will go with|it was agreed|confirmed)\b",
        "action": r"\b(will|shall|to do|action|follow up|follow-up|responsible|in charge|by (monday|tuesday|wednesday|"
                  r"thursday|friday|saturday|sunday|tomorrow|next week|end of)|deadline|send|prepare|submit|share)\b",
        "question": r"(\?$|\b(not sure|unclear|to be confirmed|tbc|need to check|pending)\b)",
    },
    "fr": {
        "decision": r"\b(convenu|décidé|décision|approuvée?s?|adopté|validé|il a été convenu|confirmé)\b",
        "action": r"\b(va|vont|doit|doivent|devra|se charge|responsable|action|d'ici|avant (lundi|mardi|mercredi|"
                  r"jeudi|vendredi|samedi|dimanche|demain|la semaine)|envoyer|préparer|soumettre|partager|relancer)\b",
        "question": r"(\?$|\b(pas sûr|à confirmer|à vérifier|en attente)\b)",
    },
}
LABELS = {
    "en": {"title": "Minutes (draft)", "present": "Present", "agenda": "Agenda", "summary": "Summary of discussion",
           "decisions": "Decisions", "actions": "Action points", "questions": "Open questions", "none": "None noted.",
           "note": "Drafted automatically from the live notes. Check names, figures and dates before saving."},
    "fr": {"title": "Compte rendu (brouillon)", "present": "Présents", "agenda": "Ordre du jour",
           "summary": "Résumé des échanges", "decisions": "Décisions", "actions": "Actions à mener",
           "questions": "Questions en suspens", "none": "Aucune notée.",
           "note": "Rédigé automatiquement à partir des notes en direct. Vérifiez les noms, chiffres et dates avant "
                   "d'enregistrer."},
}
FILLER = re.compile(r"^(ok(ay)?|yes|no|yeah|right|so|um+|uh+|hmm+|thank you|thanks|d'accord|oui|non|merci|bon|alors)"
                    r"[\s,.!]*$", re.I)
GREETING = re.compile(r"^(good (morning|afternoon|evening)|hello|hi|welcome|thank you (all|everyone)|bonjour|bonsoir|"
                      r"bienvenue|merci (à tous|beaucoup))\b[^.?!]{0,40}[.!]?$", re.I)
TIMESTAMP = re.compile(r"^\s*\[\d{1,2}:\d{2}\]\s*")


def sentences(transcript):
    out = []
    for line in (transcript or "").splitlines():
        line = TIMESTAMP.sub("", line).strip()
        for part in re.split(r"(?<=[.!?])\s+", line):
            part = part.strip(" -•\t")
            if len(part) >= 4 and not FILLER.match(part) and not GREETING.match(part):
                out.append(part[0].upper() + part[1:])
    return out


def _dedupe(items):
    seen, out = set(), []
    for s in items:
        key = re.sub(r"\W+", " ", s.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            out.append(s)
    return out


def rule_draft(transcript, lang="en", title="", when="", present=(), agenda=""):
    lang = lang if lang in CUES else "en"
    cue = {k: re.compile(v, re.I) for k, v in CUES[lang].items()}
    lab = LABELS[lang]
    said = _dedupe(sentences(transcript))
    decisions = [s for s in said if cue["decision"].search(s)]
    actions = [s for s in said if s not in decisions and cue["action"].search(s)]
    questions = [s for s in said if s not in decisions and s not in actions and cue["question"].search(s)]
    rest = [s for s in said if s not in decisions and s not in actions and s not in questions]
    # summary: the most informative remaining sentences, kept in the order they were said
    ranked = sorted(rest, key=lambda s: -len(set(re.findall(r"\w{4,}", s.lower()))))[:8]
    summary = [s for s in rest if s in ranked]

    def block(head, items):
        return [f"{head}:"] + ([f"- {i}" for i in items] if items else [f"- {lab['none']}"]) + [""]

    lines = [f"{lab['title']} — {title}".rstrip(" —"), when, ""] if title else [lab["title"], ""]
    if present:
        lines += [f"{lab['present']}: " + ", ".join(present), ""]
    if agenda and agenda.strip():
        lines += [f"{lab['agenda']}:"] + [f"- {a.strip(' -•')}" for a in agenda.splitlines() if a.strip()] + [""]
    lines += block(lab["summary"], summary)
    lines += block(lab["decisions"], decisions[:15])
    lines += block(lab["actions"], actions[:20])
    if questions:
        lines += block(lab["questions"], questions[:10])
    lines.append(f"({lab['note']})")
    return "\n".join(line for line in lines if line is not None).strip()


def ai_draft(transcript, lang="en", agenda=""):
    """The AI service writes the draft. Only the redacted transcript and the agenda headings are sent."""
    lab = LABELS[lang if lang in LABELS else "en"]
    language = "French" if lang == "fr" else "English"
    system = (
        "You write meeting minutes for an organization. Use ONLY what is in the transcript; never invent names, "
        "figures, dates or decisions. The transcript comes from automatic speech recognition, so fix obvious "
        f"recognition mistakes but keep the meaning. Write in {language}, plain text without markdown symbols "
        "other than '- ' bullets, with exactly these headings in this order: "
        f"'{lab['summary']}:', '{lab['decisions']}:', '{lab['actions']}:' (each as 'what — who — by when' when said), "
        f"and '{lab['questions']}:' only if there are any. Write '{lab['none']}' under an empty heading. "
        "Keep it under 450 words.")
    content = f"Agenda:\n{redact(agenda or '-')}\n\nTranscript:\n{redact(transcript)[:MAX_TRANSCRIPT]}"
    body = json.dumps({
        "model": current_app.config.get("HELP_AI_MODEL", "claude-haiku-5-5"),
        "max_tokens": 1500, "system": system,
        "messages": [{"role": "user", "content": content}],
    }).encode()
    url = current_app.config.get("HELP_AI_URL", "https://api.anthropic.com/v1/messages")
    if not url.startswith("https://"):
        raise RuntimeError("HELP_AI_URL must start with https://")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "x-api-key": _api_key(), "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    text = "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text").strip()
    if not text:
        raise RuntimeError("empty draft")
    return text


def draft_minutes(transcript, lang="en", title="", when="", present=(), agenda=""):
    """(text, source): source is 'ai' or 'rules'. Falls back to the built-in draft if the AI service fails."""
    transcript = (transcript or "")[:MAX_TRANSCRIPT]
    lab = LABELS[lang if lang in LABELS else "en"]
    if _api_key():
        try:
            body = ai_draft(transcript, lang, agenda)
            head = [f"{lab['title']} — {title}", when, ""] if title else []
            if present:
                head += [f"{lab['present']}: " + ", ".join(present), ""]
            return "\n".join(head + [body, "", f"({lab['note']})"]).strip(), "ai"
        except Exception as exc:  # noqa: BLE001 - any failure: the built-in draft still works
            current_app.logger.warning("AI minutes draft failed: %s", exc)
    return rule_draft(transcript, lang, title, when, present, agenda), "rules"
