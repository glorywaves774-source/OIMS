"""Organization reports (Phase 7).

Every report is a function that returns one dictionary — summary figures, charts and tables — and that
same dictionary feeds the screen, CSV, Excel and PDF, so all formats always agree. Each report checks
the permission of the module its data comes from and only uses records the person may see, so a report
never shows more than the pages it summarizes.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median
from typing import Callable

from flask import g
from sqlalchemy import func, select

from app.extensions import db
from app.rbac import DEPT, ORG, can, scope_of

ZERO = Decimal(0)


# --- filters -----------------------------------------------------------------------------------

@dataclass
class Filters:
    start: date
    end: date
    owner: object = None          # a Programme or Project, or None for everything visible
    with_projects: bool = True    # a programme filter also covers its projects
    department_id: int = None

    @property
    def label(self):
        bits = [f"{self.start:%d %b %Y} – {self.end:%d %b %Y}"]
        if self.owner is not None:
            bits.append(f"{self.owner.code}{' and its projects' if self.owner.kind == 'programme' and self.with_projects else ''}")
        return " · ".join(bits)


def default_filters():
    today = date.today()
    return Filters(start=today.replace(month=1, day=1), end=today)


def owners(f, code):
    """Programmes and projects the person can see for ``code`` (e.g. finance.view), narrowed by the filter."""
    from app.programme_logic import can_see, visible_owner_stmt
    out = []
    for kind in ("programme", "project"):
        for o in db.session.execute(visible_owner_stmt(kind).order_by("code")).scalars():
            if not can_see(code, o):
                continue
            if f.owner is not None:
                if o.kind == f.owner.kind and o.id == f.owner.id:
                    pass
                elif f.owner.kind == "programme" and f.with_projects and o.kind == "project" and \
                        o.programme_id == f.owner.id:
                    pass
                else:
                    continue
            out.append(o)
    return out


def _month_keys(start, end, limit=24):
    keys, d = [], date(start.year, start.month, 1)
    while d <= end and len(keys) < limit:
        keys.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return keys


def _month_series(dates_values, start, end):
    keys = _month_keys(start, end)
    totals = OrderedDict((k, ZERO) for k in keys)
    for d, v in dates_values:
        k = date(d.year, d.month, 1)
        if k in totals:
            totals[k] += Decimal(v or 0)
    return [(k.strftime("%b %Y" if len(keys) > 12 else "%b"), v) for k, v in totals.items()]


def pct(a, b):
    return float(Decimal(a) / Decimal(b) * 100) if b else None


def elapsed_pct(o, on):
    if not (o.start_date and o.end_date) or o.end_date <= o.start_date:
        return None
    return max(0.0, min(100.0, (on - o.start_date).days / (o.end_date - o.start_date).days * 100))


def bars(title, rows, fmt="int", note=None, unit=None):
    """A horizontal bar chart: one series, sorted largest first. rows = [(label, value)]."""
    rows = [(str(lbl), v) for lbl, v in rows if v is not None]
    return {"kind": "bars", "title": title, "rows": rows, "fmt": fmt, "note": note, "unit": unit}


def columns(title, rows, fmt="int", note=None):
    """A column chart over time (months, oldest first). rows = [(label, value)]."""
    return {"kind": "columns", "title": title, "rows": rows, "fmt": fmt, "note": note}


def table(key, title, cols, rows, total=None, note=None):
    """cols = [(key, label, fmt)]; fmt in text/int/num/money/pct/date."""
    return {"key": key, "title": title, "columns": cols, "rows": rows, "total": total, "note": note}


# --- registry ----------------------------------------------------------------------------------

@dataclass
class Report:
    key: str
    title: str
    description: str
    group: str
    allowed: Callable
    build: Callable
    uses_owner: bool = True
    uses_department: bool = False
    notes: list = field(default_factory=list)


REPORTS = OrderedDict()


def report(key, title, description, group, allowed, uses_owner=True, uses_department=False):
    def deco(fn):
        REPORTS[key] = Report(key, title, description, group, allowed, fn, uses_owner, uses_department)
        return fn
    return deco


def available():
    return [r for r in REPORTS.values() if r.allowed()]


def run(r, f):
    data = r.build(f)
    data.setdefault("summary", [])
    data.setdefault("charts", [])
    data.setdefault("tables", [])
    data.setdefault("notes", [])
    data.update({"key": r.key, "title": r.title, "filters": f.label, "generated": date.today().isoformat(),
                 "organization": g.tenant.name})
    return data


def _currency_note(currencies):
    if len(currencies) > 1:
        return (f"Amounts are in {', '.join(sorted(currencies))}; totals here are per currency (the Budget and "
                "spending report also combines them using the organization's exchange rates).")
    return None


# ====================================================================================
# Programme & project reports
# ====================================================================================

@report("portfolio", "Portfolio summary", "Every programme and project with status, budget use, activities and "
        "indicators.", "Programmes & projects", lambda: can("programmes.view") or can("projects.view"))
def portfolio(f):
    from app.programme_logic import achievement, activity_counts, finance_summary, indicator_actual
    from app.models import Indicator
    rows, totals, chart = [], {}, []
    status_count = OrderedDict()
    for o in owners(f, "programmes.view"):
        fin = finance_summary(o) if can_finance(o) else None
        acts = activity_counts(o)
        done = acts["by_status"].get("completed", 0)
        inds = Indicator.query.filter_by(**{o.fk: o.id}, is_active=True).all()
        on_track = sum(1 for i in inds if (achievement(i, indicator_actual(i, None, f.end)) or 0) >=
                       (elapsed_pct(o, f.end) or 0) - 10 and indicator_actual(i, None, f.end) is not None)
        status_count[o.status] = status_count.get(o.status, 0) + 1
        row = {"code": o.code, "title": o.title, "kind": o.kind.capitalize(), "status": o.status.replace("_", " "),
               "manager": o.manager.full_name if o.manager else "", "time": elapsed_pct(o, f.end),
               "budget": fin["budget"] if fin else None, "spent": fin["spent"] if fin else None,
               "used": fin["utilization"] if fin else None, "currency": o.currency,
               "activities": f"{done} / {acts['total']}", "overdue": acts["overdue"],
               "indicators": f"{on_track} / {len(inds)}" if inds else "—"}
        rows.append(row)
        if fin:
            t = totals.setdefault(o.currency, {"budget": ZERO, "spent": ZERO})
            t["budget"] += fin["budget"]
            t["spent"] += fin["spent"]
            if fin["utilization"] is not None:
                chart.append((o.code, fin["utilization"]))
    summary = [{"label": "Programmes and projects", "value": len(rows), "fmt": "int"},
               {"label": "Active", "value": status_count.get("active", 0), "fmt": "int"},
               {"label": "Activities overdue", "value": sum(r["overdue"] for r in rows), "fmt": "int"}]
    for cur, t in totals.items():
        summary.append({"label": f"Budget used ({cur})", "value": pct(t["spent"], t["budget"]), "fmt": "pct"})
    return {"summary": summary,
            "charts": [bars("Budget used, by programme and project (%)", sorted(chart, key=lambda r: -r[1]), "pct",
                            "Compare with the share of time elapsed in the table: spending far ahead or behind time "
                            "deserves a look."),
                       bars("Programmes and projects by status", [(k.replace("_", " ").capitalize(), v)
                                                                   for k, v in status_count.items()])],
            "tables": [table("portfolio", "Programmes and projects",
                             [("code", "Code", "text"), ("title", "Title", "text"), ("kind", "Type", "text"),
                              ("status", "Status", "text"), ("manager", "Manager", "text"),
                              ("time", "Time elapsed", "pct"), ("currency", "Currency", "text"),
                              ("budget", "Budget", "money"), ("spent", "Spent", "money"), ("used", "Used", "pct"),
                              ("activities", "Activities done", "text"), ("overdue", "Overdue", "int"),
                              ("indicators", "Indicators on track", "text")], rows)],
            "notes": ["A programme's row shows only its own budget lines; its projects have their own rows.",
                      "An indicator is on track when its progress is no more than 10 points behind the share of "
                      "time elapsed. Budget figures appear only where you may see finance."]
            + ([_currency_note(totals)] if _currency_note(totals) else [])}


def can_finance(o):
    from app.programme_logic import can_see
    return can("finance.view") and can_see("finance.view", o)


@report("indicators", "Indicator performance", "Progress of every indicator towards its target, with on-track "
        "status.", "Programmes & projects", lambda: can("meal.view"))
def indicators(f):
    from app.programme_logic import achievement, indicator_actual, period_target
    from app.models import Indicator
    rows, status_count = [], OrderedDict([("Achieved", 0), ("On track", 0), ("Behind", 0), ("No data yet", 0)])
    for o in owners(f, "meal.view"):
        expected = elapsed_pct(o, f.end)
        for ind in Indicator.query.filter_by(**{o.fk: o.id}, is_active=True).order_by(Indicator.code):
            actual = indicator_actual(ind, None, f.end)
            in_period = indicator_actual(ind, f.start, f.end)
            ach = achievement(ind, actual)
            if actual is None:
                st = "No data yet"
            elif ach is not None and ach >= 100:
                st = "Achieved"
            elif ach is not None and ach >= (expected or 0) - 10:
                st = "On track"
            else:
                st = "Behind"
            status_count[st] += 1
            rows.append({"owner": o.code, "code": ind.code or "", "name": ind.name, "unit": ind.unit,
                         "baseline": ind.baseline_value, "target": ind.target_value,
                         "period_target": period_target(ind, f.start, f.end), "period": in_period,
                         "actual": actual, "achievement": ach, "expected": expected, "status": st})
    return {"summary": [{"label": "Indicators", "value": len(rows), "fmt": "int"}] +
            [{"label": k, "value": v, "fmt": "int"} for k, v in status_count.items()],
            "charts": [bars("Indicators by status", list(status_count.items()))],
            "tables": [table("indicators", "Indicators",
                             [("owner", "Programme / project", "text"), ("code", "Code", "text"),
                              ("name", "Indicator", "text"), ("baseline", "Baseline", "num"),
                              ("target", "Target", "num"), ("period_target", "Target for the period", "num"),
                              ("period", "Result in the period", "num"), ("actual", "Result to date", "num"),
                              ("achievement", "Progress", "pct"), ("expected", "Time elapsed", "pct"),
                              ("status", "Status", "text")], rows)],
            "notes": ["Only results checked by a second person are counted. Programme indicators that add up include "
                      "results reported on linked project indicators.",
                      "On track: progress no more than 10 points behind the share of the programme or project's time "
                      "that has passed."]}


@report("budget", "Budget and spending", "Budget against actual spending, commitments and monthly spending.",
        "Finance", lambda: can("finance.view"))
def budget(f):
    from app.models import Expenditure
    from app.programme_logic import category_breakdown, finance_summary, of
    rows, cats, monthly, currencies = [], {}, {}, set()
    for o in owners(f, "finance.view"):
        fin = finance_summary(o)
        period = sum((Decimal(e.amount) for e in Expenditure.query.filter(
            of(Expenditure, o), Expenditure.kind == "expenditure", Expenditure.status == "approved",
            Expenditure.spent_on >= f.start, Expenditure.spent_on <= f.end)), ZERO)
        rows.append({"code": o.code, "title": o.title, "currency": o.currency, "budget": fin["budget"],
                     "period": period, "spent": fin["spent"], "committed": fin["committed"],
                     "available": fin["available"], "used": fin["utilization"], "time": elapsed_pct(o, f.end)})
        currencies.add(o.currency)
        for c in category_breakdown(o):
            k = (o.currency, c["category"])
            t = cats.setdefault(k, {"currency": o.currency, "category": c["category"], "amount": ZERO, "spent": ZERO,
                                    "committed": ZERO})
            for m in ("amount", "spent", "committed"):
                t[m] += c[m]
        for d, v in db.session.execute(select(Expenditure.spent_on, Expenditure.amount).where(
                of(Expenditure, o), Expenditure.kind == "expenditure", Expenditure.status == "approved",
                Expenditure.spent_on >= f.start, Expenditure.spent_on <= f.end)):
            monthly.setdefault(o.currency, []).append((d, v))
    for c in cats.values():
        c["available"] = c["amount"] - c["spent"] - c["committed"]
        c["used"] = pct(c["spent"], c["amount"])
    main = g.tenant.currency if g.tenant.currency in currencies else (sorted(currencies)[0] if currencies else None)
    # Combined in the organization's currency: positions at the rates of the report's end date, spending in the
    # period at the rate of each payment's own day. Currencies without a rate are left out and named.
    base, combined, fx_notes = g.tenant.currency, None, []
    if currencies and currencies != {base}:
        from app.fx import Rates
        fx = Rates()
        as_of = min(f.end, date.today())
        combined = {"budget": ZERO, "period": ZERO, "available": ZERO}
        missing, conv_monthly, early = set(), [], set()
        for r in rows:
            rate = fx.rate(r["currency"], base, as_of)
            if rate is None:
                missing.add(r["currency"])
                continue
            combined["budget"] += (r["budget"] * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            combined["available"] += (r["available"] * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for cur, items in monthly.items():
            if cur in missing:
                continue
            for d, v in items:
                rate = fx.rate(cur, base, d)
                if rate is None:   # paid before the first rate was entered: use the earliest rate (and say so)
                    rate = fx.rate(cur, base, as_of)
                    if rate is not None:
                        early.add(cur)
                if rate is None:
                    missing.add(cur)
                    continue
                conv = (Decimal(v) * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                combined["period"] += conv
                conv_monthly.append((d, conv))
        fx_notes.append(f"Combined totals are in {base}: budget and available at the exchange rates of "
                        f"{as_of:%d %b %Y}, spending in the period at the rate of the day of each payment."
                        + (f" Payments in {', '.join(sorted(early))} made before the first rate was entered use the "
                           "rate in force on the end date." if early else "")
                        + (f" Not included (no exchange rate yet): {', '.join(sorted(missing))}." if missing else ""))
    summary = []
    if combined is not None:
        summary += [{"label": f"Budget, all together ({base})", "value": combined["budget"], "fmt": "money"},
                    {"label": f"Spent in the period, all together ({base})", "value": combined["period"],
                     "fmt": "money"},
                    {"label": f"Available, all together ({base})", "value": combined["available"], "fmt": "money"}]
    for cur in sorted(currencies):
        rs = [r for r in rows if r["currency"] == cur]
        summary += [{"label": f"Budget ({cur})", "value": sum((r["budget"] for r in rs), ZERO), "fmt": "money"},
                    {"label": f"Spent in the period ({cur})", "value": sum((r["period"] for r in rs), ZERO),
                     "fmt": "money"},
                    {"label": f"Available ({cur})", "value": sum((r["available"] for r in rs), ZERO), "fmt": "money"}]
    charts = []
    if combined is not None and conv_monthly:
        charts.append(columns(f"Approved spending per month, all together ({base})",
                              _month_series(conv_monthly, f.start, f.end), "money"))
    elif main:
        charts.append(columns(f"Approved spending per month ({main})", _month_series(monthly.get(main, []), f.start,
                                                                                     f.end), "money"))
        charts.append(bars(f"Spent to date by budget category ({main})",
                           sorted([(c["category"], c["spent"]) for c in cats.values() if c["currency"] == main],
                                  key=lambda r: -r[1]), "money"))
    return {"summary": summary, "charts": charts,
            "tables": [table("owners", "By programme and project",
                             [("code", "Code", "text"), ("title", "Title", "text"), ("currency", "Currency", "text"),
                              ("budget", "Budget", "money"), ("period", "Spent in the period", "money"),
                              ("spent", "Spent to date", "money"), ("committed", "Committed", "money"),
                              ("available", "Available", "money"), ("used", "Used", "pct"),
                              ("time", "Time elapsed", "pct")], rows),
                       table("categories", "By budget category",
                             [("currency", "Currency", "text"), ("category", "Category", "text"),
                              ("amount", "Budget", "money"), ("spent", "Spent", "money"),
                              ("committed", "Committed", "money"), ("available", "Available", "money"),
                              ("used", "Used", "pct")],
                             sorted(cats.values(), key=lambda c: (c["currency"], -c["amount"])))],
            "notes": ["Each programme's row covers only its own budget lines, so adding rows never counts money "
                      "twice. Spending counts approved expenditure only; commitments are money reserved for orders "
                      "and contracts not yet paid."] + fx_notes}


@report("donors", "Donor funding", "Funding committed and received from each donor, and the work it supports.",
        "Finance", lambda: can("finance.view"))
def donors(f):
    from app.models import FundingAgreement, FundingReceipt
    rows, by_donor = [], {}
    for o in owners(f, "finance.view"):
        for a in FundingAgreement.query.filter_by(**{o.fk: o.id}):
            received = sum((Decimal(r.amount) for r in FundingReceipt.query.filter_by(agreement_id=a.id)
                            if r.received_on <= f.end), ZERO)
            in_period = sum((Decimal(r.amount) for r in FundingReceipt.query.filter_by(agreement_id=a.id)
                             if f.start <= r.received_on <= f.end), ZERO)
            name = a.donor.name if a.donor else "—"
            rows.append({"donor": name, "owner": o.code, "reference": a.reference or "", "currency": o.currency,
                         "committed": a.committed_amount, "received": received, "period": in_period,
                         "outstanding": Decimal(a.committed_amount) - received,
                         "share": pct(received, a.committed_amount)})
            k = (name, o.currency)
            d = by_donor.setdefault(k, {"donor": name, "currency": o.currency, "committed": ZERO, "received": ZERO})
            d["committed"] += Decimal(a.committed_amount)
            d["received"] += received
    main = g.tenant.currency
    return {"summary": [{"label": "Funding agreements", "value": len(rows), "fmt": "int"},
                        {"label": "Donors", "value": len({r["donor"] for r in rows}), "fmt": "int"}] +
            [{"label": f"Received ({cur})", "value": sum((r["received"] for r in rows if r["currency"] == cur), ZERO),
              "fmt": "money"} for cur in sorted({r["currency"] for r in rows})],
            "charts": [bars(f"Received to date by donor ({main})",
                            sorted([(d["donor"], d["received"]) for d in by_donor.values() if d["currency"] == main],
                                   key=lambda r: -r[1]), "money")],
            "tables": [table("agreements", "Funding agreements",
                             [("donor", "Donor", "text"), ("owner", "Programme / project", "text"),
                              ("reference", "Reference", "text"), ("currency", "Currency", "text"),
                              ("committed", "Committed", "money"), ("received", "Received to date", "money"),
                              ("period", "Received in the period", "money"),
                              ("outstanding", "Still to receive", "money"), ("share", "Received", "pct")],
                             sorted(rows, key=lambda r: (r["donor"], r["owner"])))]}


@report("activities", "Activities", "Planned, completed and overdue activities, and people taking part.",
        "Programmes & projects", lambda: can("programmes.view") or can("projects.view"))
def activities(f):
    from app.models import Activity, ActivityReport
    from app.programme_logic import of
    rows, by_status = [], OrderedDict()
    reports_n = female = male = 0
    for o in owners(f, "programmes.view"):
        acts = [a for a in Activity.query.filter(of(Activity, o)).all()
                if (not a.planned_start or a.planned_start <= f.end) and (not a.planned_end or a.planned_end >= f.start)]
        st = {}
        for a in acts:
            st[a.status] = st.get(a.status, 0) + 1
            by_status[a.status] = by_status.get(a.status, 0) + 1
        reps = ActivityReport.query.join(Activity).filter(of(Activity, o), ActivityReport.report_date >= f.start,
                                                          ActivityReport.report_date <= f.end).all()
        rf, rm = sum(r.participants_female for r in reps), sum(r.participants_male for r in reps)
        reports_n += len(reps)
        female += rf
        male += rm
        overdue = sum(1 for a in acts if a.status in Activity.OPEN and a.planned_end and a.planned_end < date.today())
        rows.append({"code": o.code, "title": o.title, "total": len(acts), "completed": st.get("completed", 0),
                     "in_progress": st.get("in_progress", 0), "planned": st.get("planned", 0), "overdue": overdue,
                     "done": pct(st.get("completed", 0), len(acts)), "reports": len(reps), "female": rf, "male": rm})
    return {"summary": [{"label": "Activities in the period", "value": sum(r["total"] for r in rows), "fmt": "int"},
                        {"label": "Completed", "value": by_status.get("completed", 0), "fmt": "int"},
                        {"label": "Overdue", "value": sum(r["overdue"] for r in rows), "fmt": "int"},
                        {"label": "Session reports", "value": reports_n, "fmt": "int"},
                        {"label": "Participants (head-count)", "value": female + male, "fmt": "int"}],
            "charts": [bars("Activities by status", [(k.replace("_", " ").capitalize(), v)
                                                     for k, v in sorted(by_status.items(), key=lambda kv: -kv[1])]),
                       bars("Share of activities completed (%)", sorted([(r["code"], r["done"]) for r in rows
                                                                        if r["done"] is not None],
                                                                       key=lambda r: -r[1]), "pct")],
            "tables": [table("activities", "By programme and project",
                             [("code", "Code", "text"), ("title", "Title", "text"), ("total", "Activities", "int"),
                              ("completed", "Completed", "int"), ("in_progress", "In progress", "int"),
                              ("planned", "Planned", "int"), ("overdue", "Overdue", "int"),
                              ("done", "Completed", "pct"), ("reports", "Session reports", "int"),
                              ("female", "Female participants", "int"), ("male", "Male participants", "int")], rows)],
            "notes": ["Activities count when their planned dates overlap the period. Participants are head-counts "
                      "from session reports and may include the same person more than once; see the Beneficiaries "
                      "report for people counted once."]}


# ====================================================================================
# MEAL
# ====================================================================================

@report("beneficiaries", "Beneficiaries reached", "Registered people reached, each counted once, by sex, age, "
        "disability and place.", "MEAL & accountability", lambda: can("beneficiaries.view"))
def beneficiaries(f):
    from app.meal_logic import owner_in_scope, reach, reached_ids_stmt
    from app.models import Beneficiary
    from app.models.meal import AGE_BANDS, SEXES
    os_ = [o for o in owners(f, "programmes.view") if owner_in_scope("beneficiaries.view", o)]
    rows, ids = [], set()
    for o in os_:
        r = reach(o, f.start, f.end, include_projects=False)
        ids |= set(db.session.execute(reached_ids_stmt(o, f.start, f.end, include_projects=False)).scalars())
        rows.append({"code": o.code, "title": o.title, "total": r["total"], "female": r["female"], "male": r["male"],
                     "other": r["other"], "disability": r["disability"]})
    people = []
    id_list = sorted(ids)
    for i in range(0, len(id_list), 900):
        people += db.session.execute(select(Beneficiary).where(Beneficiary.id.in_(id_list[i:i + 900]),
                                                               Beneficiary.status != "merged")).scalars().all()
    bands = [b[0] for b in AGE_BANDS] + ["Unknown"]
    age = OrderedDict((b, {"band": b, "female": 0, "male": 0, "other": 0, "total": 0}) for b in bands)
    places = {}
    for p in people:
        a = age[p.age_band]
        a["total"] += 1
        a[p.sex if p.sex in ("female", "male") else "other"] += 1
        loc = p.location.label if p.location else "Not recorded"
        places[loc] = places.get(loc, 0) + 1
    regs = db.session.execute(select(Beneficiary.registered_on).where(
        Beneficiary.organization_id == g.tenant.id, Beneficiary.id.in_(id_list or [0]))).scalars().all()
    total = len(people)
    sex = OrderedDict((label, sum(1 for p in people if p.sex == k)) for k, label in SEXES.items())
    return {"summary": [{"label": "People reached, counted once", "value": total, "fmt": "int"},
                        {"label": "Female", "value": sex["Female"], "fmt": "int"},
                        {"label": "Male", "value": sex["Male"], "fmt": "int"},
                        {"label": "Living with a disability", "value": sum(1 for p in people if p.disability),
                         "fmt": "int"}],
            "charts": [bars("People reached by age group", [(b + (" years" if b != "Unknown" else ""), age[b]["total"])
                                                            for b in bands if age[b]["total"]]),
                       bars("People reached by place", sorted(places.items(), key=lambda kv: -kv[1])[:15]),
                       columns("Registrations per month (people reached)", _month_series(
                           [(d, 1) for d in regs], f.start, f.end))],
            "tables": [table("owners", "By programme and project", [
                ("code", "Code", "text"), ("title", "Title", "text"), ("total", "Reached", "int"),
                ("female", "Female", "int"), ("male", "Male", "int"), ("other", "Other / not stated", "int"),
                ("disability", "With disability", "int")], rows,
                total={"code": "", "title": "All, each person once", "total": total, "female": sex["Female"],
                       "male": sex["Male"], "other": sex["Other"] + sex["Not stated"],
                       "disability": sum(1 for p in people if p.disability)}),
                table("age", "By age group and sex", [("band", "Age group", "text"), ("female", "Female", "int"),
                                                      ("male", "Male", "int"), ("other", "Other / not stated", "int"),
                                                      ("total", "Total", "int")], list(age.values()))],
            "notes": ["Reached means enrolled, given a service, or recorded at an activity session during the period. "
                      "Someone reached by several programmes or projects appears in each of their rows but only once "
                      "in the total — do not add the rows."]}


@report("feedback", "Feedback and complaints", "What communities raised, how fast it was answered and how "
        "satisfied they were.", "MEAL & accountability", lambda: can("feedback.view"))
def feedback(f):
    from app.meal_logic import visible_feedback_stmt
    from app.models import Feedback
    stmt = visible_feedback_stmt().where(Feedback.received_on >= f.start, Feedback.received_on <= f.end)
    if f.owner is not None:
        stmt = stmt.where(getattr(Feedback, f.owner.fk) == f.owner.id)
    items = db.session.execute(stmt).scalars().all()
    days = [(x.responded_on - x.received_on).days for x in items if x.responded_on]
    late = sum(1 for x in items if x.due_date and ((x.responded_on and x.responded_on > x.due_date) or
                                                  (not x.responded_on and x.status in Feedback.OPEN
                                                   and x.due_date < date.today())))
    sat = [x.satisfaction for x in items if x.satisfaction in ("satisfied", "partly", "not_satisfied")]
    sensitive_all = db.session.scalar(select(func.count()).select_from(Feedback).where(
        Feedback.organization_id == g.tenant.id, Feedback.sensitive.is_(True), Feedback.received_on >= f.start,
        Feedback.received_on <= f.end))
    cat = OrderedDict((label.split(" (")[0], sum(1 for x in items if x.category == k))
                      for k, label in Feedback.CATEGORIES.items())
    chan = OrderedDict((label, sum(1 for x in items if x.channel == k)) for k, label in Feedback.CHANNELS.items())
    status_rows = [{"status": s.replace("_", " ").capitalize(), "count": sum(1 for x in items if x.status == s)}
                   for s in Feedback.STATUSES]
    return {"summary": [{"label": "Received", "value": len(items), "fmt": "int"},
                        {"label": "Still open", "value": sum(1 for x in items if x.status in Feedback.OPEN), "fmt": "int"},
                        {"label": "Answered late or overdue", "value": late, "fmt": "int"},
                        {"label": "Median days to reply", "value": median(days) if days else None, "fmt": "num"},
                        {"label": "Satisfied", "value": pct(sat.count("satisfied"), len(sat)) if sat else None,
                         "fmt": "pct"}],
            "charts": [bars("By type", sorted([(k, v) for k, v in cat.items() if v], key=lambda r: -r[1])),
                       bars("By channel", sorted([(k, v) for k, v in chan.items() if v], key=lambda r: -r[1])),
                       columns("Received per month", _month_series([(x.received_on, 1) for x in items], f.start, f.end))],
            "tables": [table("types", "By type", [("type", "Type", "text"), ("count", "Cases", "int")],
                             [{"type": k, "count": v} for k, v in cat.items()]),
                       table("status", "By status", [("status", "Status", "text"), ("count", "Cases", "int")],
                             status_rows)],
            "notes": [f"Sensitive cases (safeguarding, fraud, misconduct) received in the period: {sensitive_all}. "
                      "Their details are visible only to safeguarding staff" +
                      ("." if can("feedback.sensitive") else " and are left out of the figures above.")]}


# ====================================================================================
# Operations
# ====================================================================================

@report("procurement", "Procurement", "Purchase requests, orders, suppliers and how long buying takes.",
        "Finance", lambda: can("procurement.view"))
def procurement(f):
    from sqlalchemy.orm import selectinload
    from app.models import PurchaseOrder, PurchaseRequest
    from app.procurement_logic import po_figures_many, visible_requests_stmt
    stmt = visible_requests_stmt().where(PurchaseRequest.created_at >= f.start,
                                         PurchaseRequest.created_at < f.end + timedelta(days=1))
    if f.owner is not None:
        stmt = stmt.where(getattr(PurchaseRequest, f.owner.fk) == f.owner.id)
    reqs = db.session.execute(stmt).scalars().all()
    # All orders of these requests at once, with their items and suppliers (not one query per request/order)
    orders = db.session.execute(
        select(PurchaseOrder).where(PurchaseOrder.request_id.in_(stmt.with_only_columns(PurchaseRequest.id)),
                                    PurchaseOrder.status != "cancelled")
        .options(selectinload(PurchaseOrder.items), selectinload(PurchaseOrder.supplier),
                 selectinload(PurchaseOrder.request))).scalars().all()
    figs = po_figures_many(orders)
    by_supplier, cycle = {}, []
    for po in orders:
        cur = po.request.owner.currency
        k = (po.supplier.name, cur)
        s = by_supplier.setdefault(k, {"supplier": po.supplier.name, "currency": cur, "orders": 0, "value": ZERO,
                                       "paid": ZERO})
        s["orders"] += 1
        s["value"] += po.total
        s["paid"] += figs[po.id]["paid"]
        if po.approved_at and po.request.submitted_at:
            cycle.append((po.approved_at - po.request.submitted_at).days)
    status = OrderedDict((s.capitalize(), sum(1 for r in reqs if r.status == s)) for s in PurchaseRequest.STATUSES)
    methods = OrderedDict((PurchaseRequest.METHODS[m].split(" (")[0], sum(1 for r in reqs if r.method == m))
                          for m in PurchaseRequest.METHODS)
    main = g.tenant.currency
    return {"summary": [{"label": "Purchase requests", "value": len(reqs), "fmt": "int"},
                        {"label": "Orders", "value": len(orders), "fmt": "int"},
                        {"label": f"Ordered ({main})", "value": sum((po.total for po in orders
                                                                     if po.request.owner.currency == main), ZERO),
                         "fmt": "money"},
                        {"label": "Median days from request to approved order",
                         "value": median(cycle) if cycle else None, "fmt": "num"}],
            "charts": [bars("Requests by status", [(k, v) for k, v in status.items() if v]),
                       bars(f"Ordered by supplier ({main})", sorted(
                           [(s["supplier"], s["value"]) for s in by_supplier.values() if s["currency"] == main],
                           key=lambda r: -r[1])[:12], "money")],
            "tables": [table("suppliers", "By supplier", [("supplier", "Supplier", "text"), ("currency", "Currency", "text"),
                                                         ("orders", "Orders", "int"), ("value", "Ordered", "money"),
                                                         ("paid", "Paid", "money")],
                             sorted(by_supplier.values(), key=lambda s: -s["value"])),
                       table("methods", "By buying method", [("method", "Method", "text"), ("count", "Requests", "int")],
                             [{"method": k, "count": v} for k, v in methods.items()])],
            "notes": ["Requests created in the period. Cancelled orders are left out."]}


@report("assets", "Assets", "The asset register by category and status, with value and checks due.",
        "Finance", lambda: can("assets.view"), uses_owner=True)
def assets(f):
    from app.models import Asset
    from app.procurement_logic import visible_assets_stmt
    stmt = visible_assets_stmt().where(Asset.status != "disposed")
    if f.owner is not None:
        stmt = stmt.where(getattr(Asset, f.owner.fk) == f.owner.id)
    items = db.session.execute(stmt).scalars().all()
    cats, due = {}, 0
    for a in items:
        k = (a.category, a.currency)
        c = cats.setdefault(k, {"category": a.category, "currency": a.currency, "count": 0, "cost": ZERO, "book": ZERO,
                                "in_use": 0, "in_store": 0, "repair": 0, "lost": 0})
        c["count"] += 1
        c["cost"] += Decimal(a.cost or 0)
        c["book"] += a.book_value(f.end)
        c[{"in_use": "in_use", "in_store": "in_store", "under_repair": "repair", "lost": "lost"}[a.status]] += 1
        if not a.last_verified_on or a.last_verified_on < f.end - timedelta(days=365):
            due += 1
    disposed = db.session.execute(visible_assets_stmt().where(Asset.status == "disposed", Asset.disposed_on >= f.start,
                                                              Asset.disposed_on <= f.end)).scalars().all()
    main = g.tenant.currency
    return {"summary": [{"label": "Assets", "value": len(items), "fmt": "int"},
                        {"label": f"Book value ({main})", "value": sum((c["book"] for c in cats.values()
                                                                        if c["currency"] == main), ZERO), "fmt": "money"},
                        {"label": "Not checked in the last 12 months", "value": due, "fmt": "int"},
                        {"label": "Lost", "value": sum(c["lost"] for c in cats.values()), "fmt": "int"},
                        {"label": "Disposed in the period", "value": len(disposed), "fmt": "int"}],
            "charts": [bars(f"Book value by category ({main})", sorted(
                [(c["category"], c["book"]) for c in cats.values() if c["currency"] == main], key=lambda r: -r[1]),
                "money")],
            "tables": [table("categories", "By category", [
                ("category", "Category", "text"), ("currency", "Currency", "text"), ("count", "Assets", "int"),
                ("in_use", "In use", "int"), ("in_store", "In store", "int"), ("repair", "Under repair", "int"),
                ("lost", "Lost", "int"), ("cost", "Cost", "money"), ("book", "Book value", "money")],
                sorted(cats.values(), key=lambda c: -c["book"]))],
            "notes": ["Book value is worked out at the end of the period, falling evenly over each asset's useful life."]}


# ====================================================================================
# Office
# ====================================================================================

def _staff_allowed():
    return can("staff.records")


@report("staff", "Staff and leave", "Headcount by department and employment type, leave taken, and tasks.",
        "Office", _staff_allowed, uses_owner=False, uses_department=True)
def staff(f):
    from app.blueprints.tenant import my_department_id
    from app.models import Department, LeaveRequest, LeaveType, StaffProfile, Task
    scope = scope_of("staff.records")
    q = StaffProfile.query.filter(StaffProfile.status != "exited")
    dept = f.department_id
    if scope != ORG:
        dept = my_department_id() if scope == DEPT else -1
    if dept:
        q = q.filter(StaffProfile.department_id == dept)
    people = q.all()
    names = {d.id: d.name for d in Department.query.all()}
    by_dept, by_type = {}, {}
    for p in people:
        k = names.get(p.department_id, "No department")
        by_dept[k] = by_dept.get(k, 0) + 1
        t = p.employment_type or "Not recorded"
        by_type[t] = by_type.get(t, 0) + 1
    ids = [p.id for p in people] or [0]
    leave_rows = []
    for lt in LeaveType.query.order_by(LeaveType.name):
        reqs = LeaveRequest.query.filter(LeaveRequest.leave_type_id == lt.id, LeaveRequest.status == "approved",
                                         LeaveRequest.staff_id.in_(ids), LeaveRequest.start_date <= f.end,
                                         LeaveRequest.end_date >= f.start).all()
        if reqs:
            leave_rows.append({"type": lt.name, "requests": len(reqs), "days": sum(r.days for r in reqs),
                               "people": len({r.staff_id for r in reqs})})
    tasks_rows = []
    if can("tasks.view") and scope_of("tasks.view") in (ORG, DEPT):
        tq = Task.query.filter(Task.created_at >= f.start, Task.created_at < f.end + timedelta(days=1))
        if scope_of("tasks.view") == DEPT or dept:
            tq = tq.filter(Task.department_id == (dept or my_department_id()))
        tasks = tq.all()
        for dname, did in sorted([(names.get(i, "No department"), i) for i in {t.department_id for t in tasks}]):
            ts = [t for t in tasks if t.department_id == did]
            tasks_rows.append({"department": dname, "created": len(ts), "done": sum(1 for t in ts if t.status == "done"),
                               "overdue": sum(1 for t in ts if t.status in Task.OPEN and t.due_date
                                              and t.due_date < date.today())})
    return {"summary": [{"label": "Staff (not exited)", "value": len(people), "fmt": "int"},
                        {"label": "On leave now", "value": sum(1 for p in people if p.status == "on_leave"), "fmt": "int"},
                        {"label": "Leave days taken in the period", "value": sum(r["days"] for r in leave_rows),
                         "fmt": "int"}],
            "charts": [bars("Staff by department", sorted(by_dept.items(), key=lambda kv: -kv[1])),
                       bars("Staff by employment type", sorted(by_type.items(), key=lambda kv: -kv[1]))],
            "tables": [table("departments", "Headcount by department", [("department", "Department", "text"),
                                                                       ("count", "Staff", "int")],
                             [{"department": k, "count": v} for k, v in sorted(by_dept.items())]),
                       table("leave", "Approved leave overlapping the period", [
                           ("type", "Leave type", "text"), ("requests", "Requests", "int"), ("people", "People", "int"),
                           ("days", "Working days", "int")], leave_rows)] +
            ([table("tasks", "Tasks created in the period", [("department", "Department", "text"),
                                                             ("created", "Created", "int"), ("done", "Done", "int"),
                                                             ("overdue", "Overdue", "int")], tasks_rows)]
             if tasks_rows else []),
            "notes": ["Leave days are the working days of each approved request that overlaps the period (whole "
                      "requests, not split at the period's edges)."]}
