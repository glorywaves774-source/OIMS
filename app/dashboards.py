"""Charts for the dashboards (workspace, MEAL, finance, Kayron platform).

Each function returns chart data in the same shape as the reports (app/analytics.py: ``bars`` and ``columns``),
drawn by templates/analytics/_charts.html, so every chart looks and behaves the same: one series, values
written on the bars, hover/focus tips, no colour-only meaning. Callers check permissions; the queries here only
count what the caller is allowed to see. Counting is done in the database (grouped), not by loading records.
"""
from collections import OrderedDict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import extract, func, select

from app.analytics import bars, columns
from app.extensions import db

MONTHS_BACK = 12


def _month_starts(n=MONTHS_BACK, today=None):
    today = today or date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(date(y, m, 1))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))


def month_label(d, i):
    """Short month labels: the year only on the first month and on each January ("Dec 25", "Jan 26", "Feb")."""
    return d.strftime("%b %y") if i == 0 or d.month == 1 else d.strftime("%b")


def monthly_counts(column, where, title, n=MONTHS_BACK, note=None, fmt="int", value=None):
    """Columns for the last n months: count (or sum of `value`) of rows per month of `column`."""
    months = _month_starts(n)
    start = months[0]
    y, m = extract("year", column), extract("month", column)
    agg = func.count() if value is None else func.coalesce(func.sum(value), 0)
    rows = db.session.execute(select(y, m, agg).where(*where, column >= start).group_by(y, m)).all()
    got = {(int(a), int(b)): v for a, b, v in rows}
    series = [(month_label(d, i), got.get((d.year, d.month), 0)) for i, d in enumerate(months)]
    if not any(v for _, v in series):
        series = []
    return columns(title, series, fmt, note)


def labelled(chart, translate=True):
    """Mark a chart whose labels are the app's own words (statuses, categories): they may be translated.
    Labels that are records (names of programmes, departments, suppliers) are never translated."""
    chart["translate_labels"] = translate
    return chart


# --- workspace dashboard ---------------------------------------------------------------------------

def my_tasks_by_status(org_id, user_id):
    from app.models import Task
    names = {"todo": "To do", "in_progress": "In progress", "blocked": "Blocked"}
    counts = dict(db.session.execute(select(Task.status, func.count()).where(
        Task.organization_id == org_id, Task.assigned_to_id == user_id, Task.status.in_(Task.OPEN))
        .group_by(Task.status)).all())
    overdue = db.session.scalar(select(func.count()).select_from(Task).where(
        Task.organization_id == org_id, Task.assigned_to_id == user_id, Task.status.in_(Task.OPEN),
        Task.due_date < date.today()))
    rows = [(names[s], counts.get(s, 0)) for s in Task.OPEN if counts.get(s)]
    if overdue:
        rows.append(("Overdue", overdue))
    return labelled(bars("My open tasks", rows, note="Overdue tasks are also counted in their status."))


def budget_use(owners, limit=8):
    """Share of each programme's / project's budget spent (its own lines only)."""
    from app.programme_logic import finance_summary
    rows = []
    for o in owners[:40]:
        f = finance_summary(o)
        if f["budget"]:
            rows.append((o.code, round(float(f["spent"] / f["budget"] * 100), 1)))
    rows.sort(key=lambda r: -r[1])
    return labelled(bars("Budget used (%)", rows[:limit], "pct",
                         note="Spent (approved) as a share of each programme's or project's own budget."
                         + (f" Showing the {limit} highest." if len(rows) > limit else "")), False)


def staff_by_department(org_id):
    from app.models import Department, StaffProfile
    rows = db.session.execute(select(func.coalesce(Department.name, "No department"), func.count())
                              .select_from(StaffProfile).outerjoin(Department, Department.id ==
                                                                   StaffProfile.department_id)
                              .where(StaffProfile.organization_id == org_id, StaffProfile.status != "exited")
                              .group_by(Department.name)).all()
    rows = sorted(((name, n) for name, n in rows if n), key=lambda r: -r[1])
    return labelled(bars("Staff by department", rows[:10]), False)


def registrations_per_month(where):
    from app.models import Beneficiary
    return monthly_counts(Beneficiary.registered_on, where, "People registered per month")


# --- MEAL dashboard --------------------------------------------------------------------------------

def distribution(title, counts, labels, note=None):
    """Bars in a fixed order (sex, age groups, categories): order carries meaning, so no sorting."""
    rows = [(labels.get(k, k), counts.get(k, 0)) for k in labels if counts.get(k)]
    return labelled(bars(title, rows, note=note))


# --- finance overview ------------------------------------------------------------------------------

def spending_per_month(owners, base, rates):
    """Approved spending per month, all programmes and projects together in the main currency
    (each payment at the rate of its day; currencies without a rate are left out and named)."""
    from app.models import Expenditure
    from app.programme_logic import of
    months = _month_starts()
    start = months[0]
    totals = OrderedDict((d, Decimal(0)) for d in months)
    missing = set()
    for o in owners:
        for day, amount in db.session.execute(select(Expenditure.spent_on, Expenditure.amount).where(
                of(Expenditure, o), Expenditure.kind == "expenditure", Expenditure.status == "approved",
                Expenditure.spent_on >= start)):
            r = rates.rate(o.currency, base, day) or rates.rate(o.currency, base)
            if r is None:
                missing.add(o.currency)
                continue
            totals[date(day.year, day.month, 1)] += (Decimal(amount) * r).quantize(Decimal("0.01"))
    series = [(month_label(d, i), v) for i, (d, v) in enumerate(totals.items())]
    if not any(v for _, v in series):
        series = []
    note = f"All programmes and projects together, in {base}."
    if missing:
        note += f" Not included (no exchange rate yet): {', '.join(sorted(missing))}."
    return columns(f"Approved spending per month ({base})", series, "money", note)


# --- Kayron platform dashboard --------------------------------------------------------------------

def organizations_by_status():
    from app.models import Organization
    names = {"active": "Active", "pending": "Pending", "suspended": "Suspended", "deactivated": "Deactivated",
             "rejected": "Rejected"}
    counts = dict(db.session.execute(select(Organization.status, func.count()).group_by(Organization.status)).all())
    return distribution("Organizations by status", counts, names)


def new_organizations_per_month():
    from app.models import Organization
    return monthly_counts(Organization.created_at, [], "New organizations per month")


def sign_ins_per_day(days=14):
    from app.models import AuditLog
    from app.models.base import utcnow
    start = (utcnow() - timedelta(days=days - 1)).date()
    day = func.date(AuditLog.created_at)
    rows = dict((str(d), n) for d, n in db.session.execute(select(day, func.count()).where(
        AuditLog.action == "auth.login", AuditLog.created_at >= start).group_by(day)).all())
    series = []
    for i in range(days):
        d = start + timedelta(days=i)
        series.append((d.strftime("%d %b") if i == 0 or d.day == 1 else d.strftime("%d"), rows.get(d.isoformat(), 0)))
    if not any(v for _, v in series):
        series = []
    return columns(f"Sign-ins per day (last {days} days)", series)
