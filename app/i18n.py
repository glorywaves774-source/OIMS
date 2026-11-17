"""Languages: English (as written) and French (translated after the page is built).

How it works
* Pages are written in English. When someone has chosen French, the finished HTML is translated piece by
  piece from a dictionary (app/static/i18n/fr.json): each text between tags, and the attributes people read
  (placeholder, title, aria-label, alt, button values, confirmation texts).
* Anything inside an element marked ``translate="no"`` is left alone: names, notes, records, the
  organization's name, codes — whatever people typed in. So are scripts, styles and form text areas.
* The dictionary has exact sentences and patterns (for sentences with a number, date or name inside:
  ``"Showing the oldest {1} of {2}."``). Dates such as "16 Nov 2026" are translated on the way.
* A piece with no translation stays in English rather than being guessed.

The choice is stored on the user (``users.language``) and in a cookie for visitors.
"""
import json
import os
import re
from functools import lru_cache

from flask import current_app, g, request
from flask_login import current_user

LANGUAGES = {"en": "English", "fr": "Français"}
DEFAULT = "en"
COOKIE = "lang"
PICK_COOKIE = "lang_pick"   # chosen on the sign-in page, adopted at sign-in

SKIP_TAGS = {"script", "style", "textarea", "pre", "code"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
ATTRS = ("placeholder", "title", "aria-label", "alt", "data-confirm", "data-confirm-label", "data-tip",
         "data-empty", "data-label-light", "data-label-dark")

TOKEN = re.compile(r"<!--.*?-->|<[^>]+>|[^<]+", re.S)
TAG = re.compile(r"<\s*(/)?\s*([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)(/)?\s*>", re.S)
ATTR = re.compile(r'(\s)([a-zA-Z-]+)="([^"]*)"')
WS = re.compile(r"\s+")
LABEL_VALUE = re.compile(r"^(.+?)(: )(.*\d.*)$")                      # "Male: 3", "Apr: 1,200.00"
SEPARATED = re.compile(r"^([·•|]\s*|)(.*?)(\s*[·•|]|)$")                 # "· Department Head ·"
CURRENCY_SUFFIX = re.compile(r"^(.+?)( \([A-Z]{3}\))$")               # "Budget (USD)"

MONTHS = {"Jan": "janv.", "Feb": "févr.", "Mar": "mars", "Apr": "avr.", "May": "mai", "Jun": "juin",
          "Jul": "juil.", "Aug": "août", "Sep": "sept.", "Oct": "oct.", "Nov": "nov.", "Dec": "déc."}
MONTHS_LONG = {"January": "janvier", "February": "février", "March": "mars", "April": "avril", "May": "mai",
               "June": "juin", "July": "juillet", "August": "août", "September": "septembre",
               "October": "octobre", "November": "novembre", "December": "décembre"}
DAYS = {"Monday": "lundi", "Tuesday": "mardi", "Wednesday": "mercredi", "Thursday": "jeudi", "Friday": "vendredi",
        "Saturday": "samedi", "Sunday": "dimanche", "Mon": "lun.", "Tue": "mar.", "Wed": "mer.", "Thu": "jeu.",
        "Fri": "ven.", "Sat": "sam.", "Sun": "dim."}
DATE_RE = re.compile(r"\b(?:(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) )?(\d{1,2}) "
                     r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|"
                     r"August|September|October|November|December)\b")
MONTH_YEAR_RE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|"
                           r"June|July|August|September|October|November|December) (\d{4})\b")


# --- the dictionary --------------------------------------------------------------------------

@lru_cache(maxsize=4)
def _load(lang, path_mtime):
    path = os.path.join(current_app.static_folder, "i18n", f"{lang}.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    exact = {WS.sub(" ", k).strip(): v for k, v in data.get("strings", {}).items()}
    patterns = []
    items = [(s, d, False) for s, d in data.get("patterns", {}).items()] + \
            [(s, d, True) for s, d in data.get("numeric_patterns", {}).items()]
    for src, dst, numeric in items:
        # "Showing the oldest {1} of {2}." -> regex with a group for each {n}
        parts = re.split(r"(\{\d+\})", WS.sub(" ", src).strip())
        rx = "".join("(.+?)" if re.fullmatch(r"\{\d+\}", p) else re.escape(p) for p in parts)
        order = [int(p[1:-1]) for p in parts if re.fullmatch(r"\{\d+\}", p)]
        patterns.append((re.compile("^" + rx + "$", re.S), dst, order, numeric))
    return exact, patterns


def dictionary(lang):
    path = os.path.join(current_app.static_folder, "i18n", f"{lang}.json")
    return _load(lang, os.path.getmtime(path))


def _dates(text):
    def day(m):
        wd, d, mon = m.group(1), m.group(2), m.group(3)
        out = f"{d} {MONTHS.get(mon) or MONTHS_LONG.get(mon, mon)}"
        return f"{DAYS[wd]} {out}" if wd else out
    text = DATE_RE.sub(day, text)
    return MONTH_YEAR_RE.sub(lambda m: f"{MONTHS.get(m.group(1)) or MONTHS_LONG.get(m.group(1))} {m.group(2)}", text)


def translate_text(text, lang):
    """One piece of text (whitespace around it is kept). Results are remembered: pages repeat labels a lot."""
    if lang == DEFAULT or not text.strip():
        return text
    path = os.path.join(current_app.static_folder, "i18n", f"{lang}.json")
    return _translate_cached(text, lang, os.path.getmtime(path))


@lru_cache(maxsize=50000)
def _translate_cached(text, lang, _mtime):
    return _translate(text, lang)


def _translate(text, lang):
    exact, patterns = dictionary(lang)
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = WS.sub(" ", text.strip())
    if core in exact:
        return lead + exact[core] + trail
    for rx, dst, order, numeric in patterns:
        m = rx.match(core)
        if m and numeric and not all(re.search(r"\d", v) for v in m.groups()):
            m = None   # only for counts and dates, never for words someone typed
        if m:
            out = dst
            for n, val in zip(order, m.groups()):
                # the filled-in parts are data (names, codes, amounts): kept as they are, dates in the language
                out = out.replace("{%d}" % n, _dates(val))
            return lead + out + trail
    # Separators around the text: "· Department Head ·" (a name or code sits on either side)
    m = SEPARATED.match(core)
    if m and m.group(2) and (m.group(1) or m.group(3)):
        inner = translate_text(m.group(2), lang)
        if inner != m.group(2):
            return lead + m.group(1) + inner + m.group(3) + trail
    # Built from parts: "Activities · PRJ/2026/001 · ZENTAVA OIMS", "Apr: 1,200.00", "Budget (USD)"
    if " · " in core:
        parts = core.split(" · ")
        new = [translate_text(p, lang) for p in parts]
        if new != parts:
            return lead + " · ".join(new) + trail
    m = LABEL_VALUE.match(core)
    if m:
        label = translate_text(m.group(1), lang)
        if label != m.group(1):
            return lead + label + m.group(2) + _dates(m.group(3)) + trail
    m = CURRENCY_SUFFIX.match(core)
    if m:
        label = translate_text(m.group(1), lang)
        if label != m.group(1):
            return lead + label + m.group(2) + trail
    dated = _dates(core)
    if dated != core:
        return lead + dated + trail
    return text


def _attr_sub(lang):
    def sub(m):
        space, name, value = m.groups()
        if name in ATTRS or name == "value":
            from markupsafe import Markup
            plain = Markup(value).unescape()
            new = translate_text(plain, lang)
            if new != plain:
                from markupsafe import escape
                return f'{space}{name}="{escape(new)}"'
        return m.group(0)
    return sub


def translate_html(html, lang):
    """Translate a finished page, leaving untouched everything marked translate="no"."""
    if lang == DEFAULT:
        return html
    from markupsafe import Markup, escape
    out, stack = [], []          # stack of (tag, keep_original)
    attr_sub = _attr_sub(lang)

    def frozen():
        return any(keep for _, keep in stack)

    for tok in TOKEN.findall(html):
        if tok.startswith("<!--"):
            out.append(tok)
            continue
        if tok.startswith("<"):
            m = TAG.match(tok)
            if not m:
                out.append(tok)
                continue
            closing, name, attrs, selfclose = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
            if closing:
                for i in range(len(stack) - 1, -1, -1):   # close the nearest matching tag
                    if stack[i][0] == name:
                        del stack[i:]
                        break
                out.append(tok)
                continue
            keep = 'translate="no"' in attrs or name in SKIP_TAGS
            # drawings: only their spoken/hover labels (<title>, <desc>) are read as text; chart text is data
            if name != "svg" and name not in ("title", "desc") and any(t == "svg" for t, _ in stack):
                keep = True
            # a drop-down choice that is a record (its value is a record number) shows typed-in data
            if name == "option" and re.search(r'value="[1-9]\d*"', attrs):
                keep = "record"   # ...except calendar month names, which are fixed words (see below)
            # attributes people read, unless this element (or a parent) is kept as typed. A "value" is data
            # sent with the form, so it is translated only on input buttons, where it is also the label.
            # scripts, styles and text boxes keep their content, but their labels (placeholder, title) are read
            attrs_kept = frozen() or 'translate="no"' in attrs or (name == "option" and keep)
            if not attrs_kept:
                label_value = name == "input" and re.search(r'type="(submit|button|reset)"', attrs) is not None
                tok = ATTR.sub(lambda mm: mm.group(0) if mm.group(2) == "value" and not label_value
                               else attr_sub(mm), tok)
            if name == "html":
                tok = re.sub(r'\slang="[^"]*"', f' lang="{lang}"', tok)
            out.append(tok)
            if name not in VOID_TAGS and not selfclose:
                stack.append((name, keep))
            continue
        if frozen() or not tok.strip():
            month = tok.strip()
            if (stack and stack[-1] == ("option", "record") and month in MONTHS_LONG
                    and not any(k is True for _, k in stack)):
                tok = tok.replace(month, translate_text(month, lang))
            out.append(tok)
            continue
        plain = Markup(tok).unescape()
        new = translate_text(plain, lang)
        out.append(str(escape(new)) if new != plain else tok)
    return "".join(out)


# --- the person's choice ---------------------------------------------------------------------

def current_language():
    if "lang" in g:
        return g.lang
    lang = None
    if current_user and current_user.is_authenticated:
        lang = getattr(current_user, "language", None)
    if not lang:
        lang = request.cookies.get(COOKIE)
    g.lang = lang if lang in LANGUAGES else DEFAULT
    return g.lang


def _adopt_pick(sender, user, **extra):
    """A language picked on the sign-in page just before signing in becomes the person's setting."""
    pick = request.cookies.get(PICK_COOKIE)
    if pick in LANGUAGES and getattr(user, "language", None) != pick:
        user.language = pick
        from app.extensions import db
        db.session.commit()
    g.pop("lang", None)
    g.drop_pick = pick is not None


def init_app(app):
    from flask_login import user_logged_in

    @app.template_filter("tr")
    def tr(text):
        """For fixed words drawn inside charts (which the page translator leaves alone), e.g. month labels."""
        return translate_text(str(text), current_language())
    user_logged_in.connect(_adopt_pick, app)

    @app.after_request
    def drop_pick(response):
        if g.get("drop_pick"):
            response.delete_cookie(PICK_COOKIE)
        return response

    @app.context_processor
    def inject_language():
        return {"lang": current_language(), "languages": LANGUAGES}

    @app.after_request
    def translate_response(response):
        if (response.status_code != 304 and not response.direct_passthrough
                and response.mimetype == "text/html" and current_language() != DEFAULT):
            html = response.get_data(as_text=True)
            response.set_data(translate_html(html, current_language()))
        return response
