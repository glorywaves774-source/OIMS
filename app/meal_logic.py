"""Who may see which beneficiaries and feedback, duplicate checks, and reach counts without double counting."""
from datetime import date

from flask import g
from flask_login import current_user
from sqlalchemy import and_, exists, false, func, or_, select, true
from sqlalchemy.orm import aliased

from app.crypto import blind_index, normalize
from app.models.meal import ConsentRecord, age_band, age_from
from app.extensions import db
from app.models import (Activity, ActivityAttendance, ActivityReport, Beneficiary, Enrollment, Feedback, Programme,
                        ProgrammeTeamMember, Project, ProjectTeamMember, ServiceRecord)
from app.rbac import DEPT, ORG, can, scope_of


def _support():
    return g.get("support_request") is not None


def _my_dept():
    from app.blueprints.tenant import my_department_id
    return my_department_id()


def owner_ids(scope):
    """(programme id select, project id select) of the owners a scope covers for the current person."""
    me = current_user.id
    pm = or_(Programme.manager_id == me, exists().where(ProgrammeTeamMember.programme_id == Programme.id,
                                                        ProgrammeTeamMember.user_id == me))
    jm = or_(Project.manager_id == me, exists().where(ProjectTeamMember.project_id == Project.id,
                                                      ProjectTeamMember.user_id == me))
    if scope == DEPT and _my_dept():
        pm = or_(pm, Programme.department_id == _my_dept())
        jm = or_(jm, Project.department_id == _my_dept())
    return select(Programme.id).where(pm), select(Project.id).where(jm)


def owner_in_scope(code, owner):
    scope = scope_of(code)
    if scope == ORG:
        return True
    if scope is None or owner is None:
        return False
    if current_user.id in owner.member_ids():
        return True
    return scope == DEPT and owner.department_id is not None and owner.department_id == _my_dept()


# --- Beneficiaries ---------------------------------------------------------------------------

def beneficiary_scope_clause(code="beneficiaries.view"):
    scope = scope_of(code)
    if scope == ORG:
        return true()
    if scope is None:
        return false()
    progs, projs = owner_ids(scope)
    e = aliased(Enrollment)   # an alias, so this works inside queries that already join Enrollment
    enrolled = exists().where(e.beneficiary_id == Beneficiary.id,
                              or_(e.programme_id.in_(progs), e.project_id.in_(projs)))
    return or_(Beneficiary.registered_by_id == current_user.id, enrolled)


def visible_beneficiaries_where(code="beneficiaries.view", include_merged=False):
    cond = [Beneficiary.organization_id == g.tenant.id, beneficiary_scope_clause(code)]
    if not include_merged:
        cond.append(Beneficiary.status != "merged")
    return cond


def visible_beneficiaries_stmt(code="beneficiaries.view", include_merged=False):
    return select(Beneficiary).where(*visible_beneficiaries_where(code, include_merged))


def _in(code, b):
    if scope_of(code) == ORG:
        return True
    return db.session.execute(select(func.count()).select_from(Beneficiary).where(
        Beneficiary.id == b.id, beneficiary_scope_clause(code))).scalar() > 0


def can_see_beneficiary(b):
    return can("beneficiaries.view") and _in("beneficiaries.view", b)


def can_see_sensitive(b):
    return can("beneficiaries.sensitive") and _in("beneficiaries.sensitive", b)


def can_update_beneficiary(b):
    """Correct details: managers, or registrars for people in their scope. Never during support access."""
    if _support() or b.status == "merged":
        return False
    if can("beneficiaries.manage") and _in("beneficiaries.manage", b):
        return True
    return can("beneficiaries.register") and _in("beneficiaries.register", b)


def can_manage_beneficiary(b):
    return not _support() and can("beneficiaries.manage") and _in("beneficiaries.manage", b)


def can_register_for(owner):
    """May enrol people in / record services and attendance for this programme or project?"""
    if _support() or owner is None or owner.status in ("closed", "cancelled"):
        return False
    return can("beneficiaries.register") and owner_in_scope("beneficiaries.register", owner)


def possible_duplicates(first_name, last_name, birth_year=None, phone=None, id_number=None, exclude_id=None):
    """Beneficiaries who may be the same person: same phone, same ID number, or same name and birth year."""
    conds = []
    if phone and blind_index(phone, "phone"):
        conds.append(Beneficiary.phone_index == blind_index(phone, "phone"))
    if id_number and blind_index(id_number, "id"):
        conds.append(Beneficiary.id_number_index == blind_index(id_number, "id"))
    if first_name and last_name:
        f, l = normalize(first_name), normalize(last_name)
        same_name = and_(func.lower(Beneficiary.first_name) == f, func.lower(Beneficiary.last_name) == l)
        if birth_year:
            same_name = and_(same_name, or_(Beneficiary.birth_year.is_(None),
                                            func.abs(Beneficiary.birth_year - birth_year) <= 1))
        conds.append(same_name)
    if not conds:
        return []
    stmt = select(Beneficiary).where(Beneficiary.organization_id == g.tenant.id, Beneficiary.status != "merged",
                                     or_(*conds))
    if exclude_id:
        stmt = stmt.where(Beneficiary.id != exclude_id)
    return db.session.execute(stmt.order_by(Beneficiary.code).limit(20)).scalars().all()


def enrollable_owners():
    """Programmes and projects the person may enrol people in (open ones only)."""
    from app.programme_logic import visible_owner_stmt
    out = []
    for kind in ("programme", "project"):
        for o in db.session.execute(visible_owner_stmt(kind).order_by("code")).scalars():
            if can_register_for(o):
                out.append(o)
    return out


# --- Reach (people counted once) ---------------------------------------------------------------

def _owner_filter(model, owner, include_projects):
    if owner.kind == "project":
        return model.project_id == owner.id
    cond = model.programme_id == owner.id
    if include_projects:
        cond = or_(cond, model.project_id.in_(select(Project.id).where(Project.programme_id == owner.id)))
    return cond


def reached_ids_stmt(owner, start=None, end=None, include_projects=True):
    """Distinct beneficiaries enrolled in, served by or attending activities of an owner (and its projects)."""
    end = end or date.today()
    e = select(Enrollment.beneficiary_id).where(_owner_filter(Enrollment, owner, include_projects),
                                                Enrollment.enrolled_on <= end,
                                                or_(Enrollment.ended_on.is_(None),
                                                    Enrollment.ended_on >= (start or date.min)))
    s = select(ServiceRecord.beneficiary_id).where(_owner_filter(ServiceRecord, owner, include_projects),
                                                   ServiceRecord.delivered_on <= end,
                                                   *([ServiceRecord.delivered_on >= start] if start else []))
    a = (select(ActivityAttendance.beneficiary_id).join(ActivityReport, ActivityReport.id == ActivityAttendance.report_id)
         .join(Activity, Activity.id == ActivityReport.activity_id)
         .where(_owner_filter(Activity, owner, include_projects), ActivityReport.report_date <= end,
                *([ActivityReport.report_date >= start] if start else [])))
    return e.union(s, a)


PROFILE_COLUMNS = (Beneficiary.id, Beneficiary.sex, Beneficiary.date_of_birth, Beneficiary.birth_year,
                   Beneficiary.disability, Beneficiary.registered_on)


def profile_rows(where=None, ids=None):
    """Just the columns needed for counting people (sex, age, disability), without loading whole records.

    Pass either SQL conditions (`where`) or a set of ids. Rows carry `.age_band` like a Beneficiary."""
    out = []
    today = date.today()
    if ids is not None:
        id_list = sorted(ids)
        chunks = [id_list[i:i + 900] for i in range(0, len(id_list), 900)]   # below database parameter limits
        conds = [[Beneficiary.id.in_(c), Beneficiary.status != "merged"] for c in chunks]
    else:
        conds = [list(where or [])]
    for cond in conds:
        for r in db.session.execute(select(*PROFILE_COLUMNS).where(*cond)):
            out.append(_Profile(r.id, r.sex, age_band(age_from(r.date_of_birth, r.birth_year, today)),
                                r.disability, r.registered_on))
    return out


class _Profile:
    __slots__ = ("id", "sex", "age_band", "disability", "registered_on")

    def __init__(self, id_, sex, band, disability, registered_on):
        self.id, self.sex, self.age_band, self.disability, self.registered_on = id_, sex, band, disability, registered_on


def consent_given_ids(where):
    """Ids (among beneficiaries matching `where`) whose most recent consent has not been withdrawn."""
    ranked = (select(ConsentRecord.beneficiary_id, ConsentRecord.withdrawn_on,
                     func.row_number().over(partition_by=ConsentRecord.beneficiary_id,
                                            order_by=(ConsentRecord.given_on.desc(), ConsentRecord.id.desc()))
                     .label("rn"))
              .join(Beneficiary, Beneficiary.id == ConsentRecord.beneficiary_id).where(*where).subquery())
    return set(db.session.execute(select(ranked.c.beneficiary_id).where(ranked.c.rn == 1,
                                                                        ranked.c.withdrawn_on.is_(None))).scalars())


def reach(owner, start=None, end=None, include_projects=True):
    ids = set(db.session.execute(reached_ids_stmt(owner, start, end, include_projects)).scalars())
    rows = profile_rows(ids=ids)
    by_sex, by_age = {}, {}
    disability = 0
    for b in rows:
        by_sex[b.sex] = by_sex.get(b.sex, 0) + 1
        by_age[b.age_band] = by_age.get(b.age_band, 0) + 1
        disability += 1 if b.disability else 0
    return {"total": len(rows), "female": by_sex.get("female", 0), "male": by_sex.get("male", 0),
            "other": by_sex.get("other", 0) + by_sex.get("not_stated", 0), "by_age": by_age,
            "disability": disability}


# --- Feedback --------------------------------------------------------------------------------

def feedback_clause():
    me = current_user.id
    mine = or_(Feedback.received_by_id == me, Feedback.assigned_to_id == me)
    scope = scope_of("feedback.view")
    if scope == ORG:
        cond = true()
    elif scope is None:
        cond = mine
    else:
        progs, projs = owner_ids(scope)
        cond = or_(mine, Feedback.programme_id.in_(progs), Feedback.project_id.in_(projs))
    if not can("feedback.sensitive"):
        # Sensitive cases are seen only by safeguarding staff and the person who took or handles them.
        cond = and_(cond, or_(Feedback.sensitive.is_(False), mine))
    return cond


def visible_feedback_stmt():
    return select(Feedback).where(Feedback.organization_id == g.tenant.id, feedback_clause())


def can_see_feedback(f):
    return db.session.execute(select(func.count()).select_from(Feedback).where(
        Feedback.id == f.id, feedback_clause())).scalar() > 0


def can_handle_feedback(f):
    """Assign, respond and close. Sensitive cases need the sensitive permission (or being the assignee)."""
    if _support() or not can_see_feedback(f):
        return False
    if f.assigned_to_id == current_user.id:
        return True
    if f.sensitive:
        return can("feedback.sensitive")
    if not can("feedback.manage"):
        return False
    scope = scope_of("feedback.manage")
    return scope == ORG or f.received_by_id == current_user.id or owner_in_scope("feedback.manage", f.owner)
