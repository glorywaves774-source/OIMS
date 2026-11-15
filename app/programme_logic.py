"""Access rules and calculations shared by programmes and projects.

Functions take an *owner* — a Programme or a Project. Both expose ``kind``, ``fk``
(the column name on shared tables), ``perm`` (permission prefix) and ``member_ids()``.
Permission codes may be written as ``programmes.<action>``; for a project they are
translated to ``projects.<action>`` automatically.
"""
from datetime import date
from decimal import Decimal

from flask import g
from flask_login import current_user
from sqlalchemy import exists, func, or_, select

from app.extensions import db
from app.models import (Activity, BudgetLine, Expenditure, FundingAgreement, FundingReceipt, Indicator,
                        IndicatorResult, Membership, Programme, ProgrammeTeamMember, Project, ProjectTeamMember,
                        StaffProfile)
from app.rbac import DEPT, ORG, OWN, can, permissions_for_role, scope_of  # noqa: F401

ZERO = Decimal("0")


# --- Owner helpers --------------------------------------------------------------------------

def own(owner):
    """Keyword arguments that attach a shared record to its owner, e.g. {"project_id": 7}."""
    return {owner.fk: owner.id}


def of(model, owner):
    """SQL condition: the shared record belongs to this owner."""
    return getattr(model, owner.fk) == owner.id


def owner_of(obj):
    """The programme or project a shared record belongs to."""
    if getattr(obj, "project_id", None):
        return db.session.get(Project, obj.project_id)
    if getattr(obj, "programme_id", None):
        return db.session.get(Programme, obj.programme_id)
    return None


def pcode(code, owner):
    if owner is not None and code.startswith("programmes."):
        return owner.perm + code[len("programmes"):]
    return code


TEAM = {"programme": (Programme, ProgrammeTeamMember, "programme_id"), "project": (Project, ProjectTeamMember, "project_id")}


# --- Access ------------------------------------------------------------------------------

def _my_department():
    from app.blueprints.tenant import my_department_id
    return my_department_id()


def allowed(code, prog):
    """Does the current person hold ``code`` for this programme/project, given their scope?"""
    code = pcode(code, prog)
    scope = scope_of(code)
    if scope == ORG:
        return True
    if scope is None:
        return False
    if current_user.id in prog.member_ids():
        return True
    return scope == DEPT and prog.department_id is not None and prog.department_id == _my_department()


def visible_owner_stmt(kind, action="view"):
    model, team, fk = TEAM[kind]
    stmt = select(model).where(model.organization_id == g.tenant.id)
    scope = scope_of(f"{model.perm}.{action}")
    if scope == ORG:
        return stmt
    if scope is None:
        return stmt.where(model.id == -1)
    me = current_user.id
    member = or_(model.manager_id == me, exists().where(getattr(team, fk) == model.id, team.user_id == me))
    if scope == DEPT and _my_department():
        return stmt.where(or_(member, model.department_id == _my_department()))
    return stmt.where(member)


def visible_programmes_stmt(code="programmes.view"):
    return visible_owner_stmt("programme", code.split(".")[1])


def visible_projects_stmt(action="view"):
    return visible_owner_stmt("project", action)


def holders(code, prog=None):
    """User ids in this organization whose role grants ``code`` covering ``prog`` (for notifications)."""
    code = pcode(code, prog)
    out = []
    for m in Membership.query.filter_by(organization_id=g.tenant.id, status=Membership.ACTIVE):
        scope = permissions_for_role(m.role).get(code) if m.role else None
        if scope == ORG:
            out.append(m.user_id)
        elif prog is not None and scope in (DEPT, OWN):
            if m.user_id in prog.member_ids():
                out.append(m.user_id)
            elif scope == DEPT and prog.department_id:
                sp = StaffProfile.query.filter_by(organization_id=g.tenant.id, user_id=m.user_id).first()
                if sp and sp.department_id == prog.department_id:
                    out.append(m.user_id)
    return out


def read_only():
    return g.get("support_request") is not None


def can_do(code, prog):
    """Allowed to change this programme/project? Closed and cancelled ones are read-only (archived)."""
    if prog is not None and prog.status in ("closed", "cancelled") and not code.endswith(".view"):
        return False
    return not read_only() and can(pcode(code, prog)) and allowed(code, prog)


def can_see(code, prog):
    return can(pcode(code, prog)) and allowed(code, prog)


# --- Finance -----------------------------------------------------------------------------

def _sum(stmt):
    return Decimal(db.session.scalar(stmt) or 0)


def finance_summary(prog):
    budget = _sum(select(func.sum(BudgetLine.amount)).where(of(BudgetLine, prog)))
    spent = _sum(select(func.sum(Expenditure.amount)).where(
        of(Expenditure, prog), Expenditure.kind == "expenditure", Expenditure.status == "approved"))
    committed = _sum(select(func.sum(Expenditure.amount)).where(
        of(Expenditure, prog), Expenditure.kind == "commitment", Expenditure.status == "approved"))
    pending = _sum(select(func.sum(Expenditure.amount)).where(
        of(Expenditure, prog), Expenditure.status == "pending"))
    funding_committed = _sum(select(func.sum(FundingAgreement.committed_amount)).where(
        of(FundingAgreement, prog)))
    funding_received = _sum(select(func.sum(FundingReceipt.amount)).join(FundingAgreement).where(
        of(FundingAgreement, prog)))
    available = budget - spent - committed
    return {
        "approved_budget": Decimal(prog.approved_budget or 0), "budget": budget, "spent": spent,
        "committed": committed, "pending": pending, "available": available,
        "utilization": float(spent / budget * 100) if budget else None,
        "burn_with_commitments": float((spent + committed) / budget * 100) if budget else None,
        "funding_committed": funding_committed, "funding_received": funding_received,
        "funding_gap": budget - funding_committed,
    }


def line_figures(line):
    spent = _sum(select(func.sum(Expenditure.amount)).where(
        Expenditure.budget_line_id == line.id, Expenditure.kind == "expenditure", Expenditure.status == "approved"))
    committed = _sum(select(func.sum(Expenditure.amount)).where(
        Expenditure.budget_line_id == line.id, Expenditure.kind == "commitment", Expenditure.status == "approved"))
    amount = Decimal(line.amount or 0)
    return {"amount": amount, "spent": spent, "committed": committed, "available": amount - spent - committed,
            "variance": amount - spent,
            "utilization": float(spent / amount * 100) if amount else None}


def category_breakdown(prog):
    rows = {}
    for line in BudgetLine.query.filter_by(**own(prog)).all():
        f = line_figures(line)
        r = rows.setdefault(line.category.name, {"category": line.category.name, "amount": ZERO, "spent": ZERO,
                                                 "committed": ZERO})
        r["amount"] += f["amount"]
        r["spent"] += f["spent"]
        r["committed"] += f["committed"]
    for r in rows.values():
        r["available"] = r["amount"] - r["spent"] - r["committed"]
        r["utilization"] = float(r["spent"] / r["amount"] * 100) if r["amount"] else None
    return sorted(rows.values(), key=lambda r: -r["amount"])


# --- Indicators ----------------------------------------------------------------------------

def contributing_ids(ind):
    """A programme indicator that adds up also counts results reported on linked project indicators."""
    if ind.programme_id and ind.aggregation == "sum":
        return [i for (i,) in db.session.execute(select(Indicator.id).where(Indicator.contributes_to_id == ind.id,
                                                                            Indicator.is_active.is_(True)))]
    return []


def indicator_actual(ind, start=None, end=None, verified_only=True, include_projects=True):
    """Aggregate actual results for an indicator over a period, following its aggregation rule.

    Every result is stored once, on exactly one indicator. A programme indicator that adds up
    includes the results of project indicators linked to it, so nothing is entered or counted twice.
    """
    ids = [ind.id] + (contributing_ids(ind) if include_projects else [])
    q = IndicatorResult.query.filter(IndicatorResult.indicator_id.in_(ids))
    if verified_only:
        q = q.filter(IndicatorResult.status == "verified")
    else:
        q = q.filter(IndicatorResult.status != "rejected")
    if start:
        q = q.filter(IndicatorResult.period_end >= start)
    if end:
        q = q.filter(IndicatorResult.period_end <= end)
    rows = q.order_by(IndicatorResult.period_end).all()
    if not rows:
        return None
    if ind.aggregation == "sum":
        return sum((Decimal(r.value) for r in rows), ZERO)
    if ind.aggregation == "max":
        return max(Decimal(r.value) for r in rows)
    # "latest": most recent period; several locations in that period are added together
    last_end = rows[-1].period_end
    return sum((Decimal(r.value) for r in rows if r.period_end == last_end), ZERO)


def achievement(ind, actual):
    """Percent of the way from baseline to target (works for increasing and decreasing indicators)."""
    if actual is None or ind.target_value is None:
        return None
    baseline = Decimal(ind.baseline_value or 0) if ind.aggregation != "sum" else ZERO
    target = Decimal(ind.target_value)
    if target == baseline:
        return 100.0 if actual == target else None
    return float((Decimal(actual) - baseline) / (target - baseline) * 100)


def overlapping_result(ind, start, end, location_id, exclude_id=None):
    """For indicators that add up, the same period and place must not be reported twice (no double counting)."""
    q = IndicatorResult.query.filter(IndicatorResult.indicator_id == ind.id, IndicatorResult.status != "rejected",
                                     IndicatorResult.period_start <= end, IndicatorResult.period_end >= start)
    if location_id:
        q = q.filter(or_(IndicatorResult.location_id == location_id, IndicatorResult.location_id.is_(None)))
    if exclude_id:
        q = q.filter(IndicatorResult.id != exclude_id)
    return q.first()


def indicator_rows(prog, start=None, end=None):
    rows = []
    for ind in Indicator.query.filter_by(**own(prog), is_active=True).order_by(Indicator.code, Indicator.id):
        actual = indicator_actual(ind, start, end)
        pending = IndicatorResult.query.filter_by(indicator_id=ind.id, status="submitted").count()
        rows.append({"ind": ind, "actual": actual, "achievement": achievement(ind, actual), "pending": pending,
                     "period_target": period_target(ind, start, end) if (start or end) else None})
    return rows


def period_target(ind, start, end):
    total, found = ZERO, False
    for t in ind.targets:
        if (not start or t.period_end >= start) and (not end or t.period_start <= end):
            total += Decimal(t.target_value)
            found = True
            if ind.aggregation != "sum":
                total = Decimal(t.target_value)
    return total if found else None


def consolidated(prog):
    """A programme with its linked projects. Each expenditure belongs to one owner only, so sums never overlap."""
    if prog.kind != "programme":
        return None
    own_fin = finance_summary(prog)
    rows, budget, spent, other = [], own_fin["budget"], own_fin["spent"], False
    for p in Project.query.filter_by(programme_id=prog.id).order_by(Project.code).all():
        f = finance_summary(p)
        if p.currency == prog.currency:
            budget += f["budget"]
            spent += f["spent"]
        else:
            other = True
        rows.append({"p": p, "fin": f, "acts": activity_counts(p), "visible": can_see("programmes.view", p)})
    return {"projects": rows, "budget": budget, "spent": spent, "other_currency": other}


# --- Activities & timeline ----------------------------------------------------------------------

def activity_counts(prog):
    counts = dict(db.session.execute(select(Activity.status, func.count()).where(
        of(Activity, prog)).group_by(Activity.status)).all())
    overdue = Activity.query.filter(of(Activity, prog), Activity.status.in_(Activity.OPEN),
                                    Activity.planned_end < date.today()).count()
    return {"by_status": counts, "total": sum(counts.values()), "overdue": overdue}


def timeline(prog, activities, milestones, width=1000, row_h=30, label_w=0):
    """Geometry for the SVG timeline (Gantt) — positions are attributes, so no inline styles are needed.

    The range fits the activities and milestones shown (not the whole programme), so bars stay readable.
    """
    from datetime import timedelta
    dates = [d for a in activities for d in (a.planned_start, a.planned_end) if d]
    dates += [m.due_date for m in milestones]
    if not dates:
        return None
    start, end = min(dates).replace(day=1), max(dates) + timedelta(days=7)
    span = max((end - start).days + 1, 30)
    plot_w = width - label_w

    def x(d):
        return round(label_w + (d - start).days / span * plot_w, 1)

    month_starts = []
    d = start
    while d <= end:
        month_starts.append(d)
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    px_per_month = plot_w / max(len(month_starts), 1)
    step = next(k for k in (1, 2, 3, 6, 12) if px_per_month * k >= 46 or k == 12)
    months = []
    for i, m in enumerate(month_starts):
        show = (m.month - 1) % step == 0 or i == 0
        label = ""
        if show:
            label = m.strftime("%b %Y") if (m.month == 1 or i == 0) and px_per_month * step >= 58 else (
                str(m.year) if m.month == 1 or i == 0 else m.strftime("%b"))
        months.append({"x": x(m), "label": label, "major": m.month == 1})
    bars = []
    today = date.today()
    for i, a in enumerate(activities):
        if not a.planned_start:
            continue
        s, e = a.planned_start, a.planned_end or a.planned_start
        late = a.status in Activity.OPEN and e < today
        w = max(x(e) - x(s) + plot_w / span, 4)
        bars.append({"y": i * row_h + 8, "x": x(s), "w": w, "a": a, "late": late, "done_w": w * (a.progress or 0) / 100})
    marks = [{"x": x(m.due_date), "m": m} for m in milestones]
    return {"width": width, "height": max(len(activities), 1) * row_h + 16, "months": months, "bars": bars,
            "marks": marks, "today_x": x(today) if start <= today <= end else None, "row_h": row_h}
