"""Programme finance: budget lines, revisions, funding and expenditure (with separation of duties)."""
from decimal import Decimal, InvalidOperation

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_login import current_user

from app import audit
from app.blueprints.programmes import child, ctx, load, need, owner_ep, route
from app.extensions import db
from app.forms import ActionForm
from app.forms_programmes import (BudgetLineForm, ExpenditureForm, FundingForm, ReceiptForm, RevisionForm,
                                  ReviewNoteForm)
from app.models import (Activity, BudgetCategory, BudgetLine, BudgetRevision, BudgetRevisionLine, Donor, Expenditure,
                        FundingAgreement, FundingReceipt, utcnow)
from app.notify import notify
from app.programme_logic import allowed, category_breakdown, finance_summary, holders, line_figures, own
from app.rbac import can
from app.tenancy import tenant_get_or_404

# Budgets can be changed directly until the programme is approved; afterwards only through a revision.
OPEN_BUDGET_STATUSES = ("draft", "planned")


def _view(prog):
    if not (can("finance.view") and allowed("finance.view", prog)):
        abort(403)


def _setup_exp(form, prog):
    form.budget_line_id.choices = [(b.id, f"{b.code + ' ' if b.code else ''}{b.description} ({b.category.name})")
                                   for b in BudgetLine.query.filter_by(**own(prog)).order_by(BudgetLine.code)]
    form.activity_id.choices = [(0, "— None —")] + [(a.id, f"{a.code + ' ' if a.code else ''}{a.title}")
                                                     for a in Activity.query.filter_by(**own(prog))]


@route("/<int:pid>/finance")
def finance(pid):
    prog = load(pid)
    _view(prog)
    lines = BudgetLine.query.filter_by(**own(prog)).order_by(BudgetLine.code, BudgetLine.id).all()
    line_rows = [(ln, line_figures(ln)) for ln in lines]
    status = request.args.get("status") or ""
    q = Expenditure.query.filter_by(**own(prog))
    if status in Expenditure.STATUSES:
        q = q.filter_by(status=status)
    expenses = q.order_by(Expenditure.spent_on.desc(), Expenditure.id.desc()).limit(200).all()
    agreements = FundingAgreement.query.filter_by(**own(prog)).all()
    revisions = BudgetRevision.query.filter_by(**own(prog)).order_by(BudgetRevision.created_at.desc()).all()
    line_form = BudgetLineForm(prefix="b")
    line_form.category_id.choices = [(c.id, c.name) for c in BudgetCategory.query.filter_by(
        organization_id=g.tenant.id).order_by(BudgetCategory.sort_order, BudgetCategory.name)]
    exp_form = ExpenditureForm(prefix="x")
    _setup_exp(exp_form, prog)
    fund_form = FundingForm(prefix="f")
    fund_form.donor_id.choices = [(d.id, d.name) for d in Donor.query.filter_by(organization_id=g.tenant.id).order_by(Donor.name)]
    rec_form = ReceiptForm(prefix="r")
    rec_form.agreement_id.choices = [(a.id, f"{a.donor.name} {a.reference or ''}".strip()) for a in agreements]
    return render_template("programmes/finance.html", fin=finance_summary(prog), cats=category_breakdown(prog),
                           line_rows=line_rows, expenses=expenses, agreements=agreements, revisions=revisions,
                           line_form=line_form, exp_form=exp_form, fund_form=fund_form, rec_form=rec_form,
                           revision_form=RevisionForm(), review_form=ReviewNoteForm(), status=status,
                           budget_open=prog.status in OPEN_BUDGET_STATUSES, **ctx(prog, "finance"))


@route("/<int:pid>/finance/lines", methods=["POST"])
@route("/<int:pid>/finance/lines/<int:lid>", methods=["POST"])
def budget_line(pid, lid=None):
    prog = load(pid)
    need("finance.record", prog)
    if prog.status not in OPEN_BUDGET_STATUSES:
        flash("The budget is approved. Request a budget revision to change it.", "warning")
        return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#budget")
    line = child(BudgetLine, lid, prog) if lid else None
    if request.form.get("delete") and line:
        if not ActionForm().validate_on_submit():
            abort(400)
        if Expenditure.query.filter_by(budget_line_id=line.id).count():
            flash("This line has expenditure recorded against it and cannot be deleted.", "danger")
        else:
            audit.record("budget.line_deleted", f"Budget line '{line.description}' deleted", entity=prog)
            db.session.delete(line)
            db.session.commit()
        return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#budget")
    form = BudgetLineForm(prefix="b")
    form.category_id.choices = [(c.id, c.name) for c in BudgetCategory.query.filter_by(organization_id=g.tenant.id)]
    if form.validate_on_submit():
        tenant_get_or_404(BudgetCategory, form.category_id.data)
        if line is None:
            line = BudgetLine(organization_id=g.tenant.id, **own(prog))
            db.session.add(line)
        line.category_id, line.code, line.description = form.category_id.data, form.code.data or None, form.description.data
        line.amount = line.original_amount = form.amount.data
        audit.record("budget.line_saved", f"Budget line '{line.description}': {line.amount}", entity=prog)
        db.session.commit()
        flash("Budget line saved.", "success")
    else:
        flash("Check the budget line: " + "; ".join(e for errs in form.errors.values() for e in errs), "danger")
    return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#budget")


@route("/<int:pid>/finance/revisions", methods=["POST"])
def revision_request(pid):
    prog = load(pid)
    need("finance.record", prog)
    form = RevisionForm()
    if not form.validate_on_submit():
        flash("Explain the reason for the revision (at least 10 characters).", "danger")
        return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
    if BudgetRevision.query.filter_by(**own(prog), status="pending").first():
        flash("A revision is already waiting for approval.", "warning")
        return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
    rev = BudgetRevision(organization_id=g.tenant.id, **own(prog), reason=form.reason.data,
                         requested_by_id=current_user.id)
    changed = 0
    for line in BudgetLine.query.filter_by(**own(prog)):
        raw = (request.form.get(f"new_{line.id}") or "").strip().replace(",", "")
        if not raw:
            continue
        try:
            new = Decimal(raw).quantize(Decimal("0.01"))
        except InvalidOperation:
            flash(f"'{raw}' is not a valid amount.", "danger")
            return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
        f = line_figures(line)
        if new < 0 or new < f["spent"] + f["committed"]:
            flash(f"'{line.description}' cannot go below what is already spent or committed ({f['spent'] + f['committed']:,.2f}).", "danger")
            return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
        if new != Decimal(line.amount):
            rev.lines.append(BudgetRevisionLine(organization_id=g.tenant.id, budget_line_id=line.id,
                                                old_amount=line.amount, new_amount=new))
            changed += 1
    if not changed:
        flash("Change at least one amount.", "warning")
        return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
    db.session.add(rev)
    db.session.flush()
    notify([u for u in holders("finance.approve", prog) if u != current_user.id], "finance",
           f"Budget revision to approve: {prog.code}", rev.reason[:200], owner_ep(prog, "finance"), pid=prog.id)
    audit.record("budget.revision_requested", f"Budget revision requested for {prog.code} ({changed} lines)", entity=prog)
    db.session.commit()
    flash("Budget revision submitted for approval.", "success")
    return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")


@route("/<int:pid>/finance/revisions/<int:rid>/<action>", methods=["POST"])
def revision_decide(pid, rid, action):
    prog = load(pid)
    need("finance.approve", prog)
    rev = child(BudgetRevision, rid, prog)
    form = ReviewNoteForm()
    if not form.validate_on_submit() or action not in ("approve", "reject") or rev.status != "pending":
        abort(400)
    if rev.requested_by_id == current_user.id:
        flash("A different person must approve a budget revision (separation of duties).", "danger")
        return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
    rev.status = "approved" if action == "approve" else "rejected"
    rev.decided_by_id, rev.decided_at, rev.decision_note = current_user.id, utcnow(), form.note.data or None
    if rev.status == "approved":
        for rl in rev.lines:
            f = line_figures(rl.budget_line)
            if rl.new_amount < f["spent"] + f["committed"]:
                db.session.rollback()
                flash(f"'{rl.budget_line.description}' now has more spent than the revised amount. Ask for a new revision.", "danger")
                return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")
            rl.budget_line.amount = rl.new_amount
    notify([rev.requested_by_id], "finance", f"Budget revision {rev.status}: {prog.code}", rev.decision_note,
           owner_ep(prog, "finance"), pid=prog.id)
    audit.record(f"budget.revision_{action}", f"Budget revision {rev.status} for {prog.code}", entity=prog,
                 details={"lines": [[rl.budget_line_id, str(rl.old_amount), str(rl.new_amount)] for rl in rev.lines]})
    db.session.commit()
    flash(f"Budget revision {rev.status}.", "success")
    return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#revisions")


@route("/<int:pid>/finance/funding", methods=["POST"])
def funding(pid):
    prog = load(pid)
    need("finance.record", prog)
    what = request.form.get("what")
    if what == "agreement":
        form = FundingForm(prefix="f")
        form.donor_id.choices = [(d.id, d.name) for d in Donor.query.filter_by(organization_id=g.tenant.id)]
        if form.validate_on_submit():
            tenant_get_or_404(Donor, form.donor_id.data)
            a = FundingAgreement(organization_id=g.tenant.id, **own(prog))
            form.populate_obj(a)
            db.session.add(a)
            audit.record("funding.agreement", f"Funding agreement {a.committed_amount} recorded", entity=prog)
            db.session.commit()
            flash("Funding agreement recorded.", "success")
        else:
            flash("Check the funding agreement details.", "danger")
    elif what == "receipt":
        form = ReceiptForm(prefix="r")
        form.agreement_id.choices = [(a.id, str(a.id)) for a in FundingAgreement.query.filter_by(**own(prog))]
        if form.validate_on_submit():
            child(FundingAgreement, form.agreement_id.data, prog)
            r = FundingReceipt(organization_id=g.tenant.id, recorded_by_id=current_user.id)
            form.populate_obj(r)
            db.session.add(r)
            audit.record("funding.receipt", f"Funding received {r.amount} on {r.received_on}", entity=prog)
            db.session.commit()
            flash("Funding receipt recorded.", "success")
        else:
            flash("Check the receipt details.", "danger")
    else:
        abort(400)
    return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#funding")


@route("/<int:pid>/finance/expenditure", methods=["POST"])
def expenditure_new(pid):
    prog = load(pid)
    need("finance.record", prog)
    form = ExpenditureForm(prefix="x")
    _setup_exp(form, prog)
    if form.validate_on_submit():
        line = child(BudgetLine, form.budget_line_id.data, prog)
        if form.activity_id.data:
            child(Activity, form.activity_id.data, prog)
        e = Expenditure(organization_id=g.tenant.id, **own(prog), recorded_by_id=current_user.id)
        form.populate_obj(e)
        e.activity_id = form.activity_id.data
        db.session.add(e)
        db.session.flush()
        avail = line_figures(line)["available"]
        if e.amount > avail:
            flash(f"Recorded, but this is more than is available on the line ({avail:,.2f}). It cannot be approved "
                  "unless the budget is revised.", "warning")
        notify([u for u in holders("finance.approve", prog) if u != current_user.id], "finance",
               f"{Expenditure.KINDS[e.kind]} to approve: {prog.code}", f"{e.description} — {prog.currency} {e.amount:,.2f}",
               owner_ep(prog, "finance"), pid=prog.id, status="pending")
        audit.record("finance.recorded", f"{e.kind.capitalize()} {e.amount} recorded on {prog.code}", entity=e)
        db.session.commit()
        flash(f"{Expenditure.KINDS[e.kind]} recorded and sent for approval.", "success")
    else:
        flash("Check the details: " + "; ".join(e for errs in form.errors.values() for e in errs), "danger")
    return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#expenditure")


@route("/<int:pid>/finance/expenditure/<int:eid>/<action>", methods=["POST"])
def expenditure_decide(pid, eid, action):
    prog = load(pid)
    e = child(Expenditure, eid, prog)
    form = ReviewNoteForm()
    if not form.validate_on_submit():
        abort(400)
    if action in ("approve", "reject"):
        need("finance.approve", prog)
        if e.status != "pending":
            abort(400)
        if e.recorded_by_id == current_user.id:
            flash("A different person must approve this (separation of financial duties).", "danger")
            return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#expenditure")
        if action == "approve" and e.amount > line_figures(e.budget_line)["available"]:
            flash("Not enough left on this budget line. Revise the budget first.", "danger")
            return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#expenditure")
        e.status = "approved" if action == "approve" else "rejected"
        e.approved_by_id, e.approved_at, e.decision_note = current_user.id, utcnow(), form.note.data or None
        notify([e.recorded_by_id], "finance", f"{Expenditure.KINDS[e.kind]} {e.status}: {e.description}",
               e.decision_note, owner_ep(prog, "finance"), pid=prog.id)
    elif action == "cancel":
        # Withdraw a pending entry, or release an approved commitment that will not be spent.
        need("finance.record", prog)
        if not (e.status == "pending" or (e.status == "approved" and e.kind == "commitment")):
            abort(400)
        e.status = "cancelled"
    else:
        abort(404)
    audit.record(f"finance.{action}", f"{e.kind.capitalize()} {e.amount} on {prog.code}: {e.status}", entity=e)
    db.session.commit()
    flash("Done.", "success")
    return redirect(url_for(owner_ep(prog, "finance"), pid=prog.id) + "#expenditure")
