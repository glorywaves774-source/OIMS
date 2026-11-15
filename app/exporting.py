"""Programme report data, and its Excel (openpyxl) and PDF (reportlab) exports.

The same ``report_data`` dictionary feeds the on-screen report, the Excel workbook and
the PDF, so all three always show the same figures. Approved reports store this
dictionary as a snapshot, so they never change afterwards.
"""
import io
from datetime import date
from decimal import Decimal

from app.analytics_export import safe_row
from app.models import Activity, Expenditure, Milestone
from app.programme_logic import (achievement, category_breakdown, consolidated, finance_summary, indicator_actual,
                                 indicator_rows, of, own)


def _f(v):
    if v is None:
        return None
    return float(v) if isinstance(v, Decimal) else v


def _reach(prog, start, end):
    """Registered people reached in the period, each counted once (programme figures include its projects)."""
    from app.meal_logic import reach
    r = reach(prog, start, end)
    return {"total": r["total"], "female": r["female"], "male": r["male"], "disability": r["disability"],
            "by_age": r["by_age"],
            "note": "Registered beneficiaries enrolled, served or recorded at an activity in the period; "
                    "each person is counted once" + (", including through the programme's projects."
                                                     if prog.kind == "programme" else ".")}


def report_data(prog, start=None, end=None, report=None):
    start = start or prog.start_date
    end = end or date.today()
    fin = finance_summary(prog)
    period_spent = sum((Decimal(e.amount) for e in Expenditure.query.filter(
        of(Expenditure, prog), Expenditure.kind == "expenditure", Expenditure.status == "approved",
        *([Expenditure.spent_on >= start] if start else []), Expenditure.spent_on <= end)), Decimal(0))
    inds = []
    for r in indicator_rows(prog, start, end):
        ind = r["ind"]
        cumulative = indicator_actual(ind, None, end)
        inds.append({"code": ind.code or "", "name": ind.name, "unit": ind.unit, "baseline": _f(ind.baseline_value),
                     "target": _f(ind.target_value), "period_target": _f(r["period_target"]),
                     "period_actual": _f(r["actual"]), "cumulative": _f(cumulative),
                     "achievement": achievement(ind, cumulative)})
    acts = []
    q = Activity.query.filter(of(Activity, prog))
    for a in q.order_by(Activity.planned_start.is_(None), Activity.planned_start, Activity.code).all():
        in_period = (not a.planned_start or not end or a.planned_start <= end) and \
                    (not a.planned_end or not start or a.planned_end >= start)
        if not in_period:
            continue
        reps = [r for r in a.reports if (not start or r.report_date >= start) and r.report_date <= end]
        acts.append({"code": a.code or "", "title": a.title, "status": a.status, "progress": a.progress,
                     "planned_start": a.planned_start.isoformat() if a.planned_start else None,
                     "planned_end": a.planned_end.isoformat() if a.planned_end else None,
                     "female": sum(r.participants_female for r in reps), "male": sum(r.participants_male for r in reps),
                     "reports": len(reps)})
    reached_f = sum(a["female"] for a in acts)
    reached_m = sum(a["male"] for a in acts)
    ms = [{"title": m.title, "due": m.due_date.isoformat(), "achieved": m.achieved_date.isoformat() if m.achieved_date else None}
          for m in Milestone.query.filter_by(**own(prog)).order_by(Milestone.due_date)
          if (not start or m.due_date >= start) and m.due_date <= end]
    challenges = [r.challenges for a in Activity.query.filter_by(**own(prog)) for r in a.reports
                  if r.challenges and (not start or r.report_date >= start) and r.report_date <= end][:10]
    data = {
        "programme": {"kind": prog.kind, "code": prog.code, "title": prog.title, "status": prog.status, "currency": prog.currency,
                      "manager": prog.manager.full_name if prog.manager else None, "sector": prog.sector,
                      "start": prog.start_date.isoformat() if prog.start_date else None,
                      "end": prog.end_date.isoformat() if prog.end_date else None, "goal": prog.goal},
        "period": {"start": start.isoformat() if start else None, "end": end.isoformat()},
        "finance": {k: _f(v) for k, v in fin.items()} | {"period_spent": _f(period_spent)},
        "categories": [{k: _f(v) for k, v in c.items()} for c in category_breakdown(prog)],
        "indicators": inds, "activities": acts, "milestones": ms,
        "participants": {"female": reached_f, "male": reached_m, "total": reached_f + reached_m,
                         "note": "Participants are counted per activity session and may include the same person more than once."},
        "reach": _reach(prog, start, end),
        "field_challenges": challenges,
        "narrative": {k: getattr(report, k) for k in ("summary", "achievements", "challenges", "lessons", "next_steps")}
        if report else {},
        "generated": date.today().isoformat(),
    }
    cons = consolidated(prog)
    if cons is not None:
        data["projects"] = [{"code": r["p"].code, "title": r["p"].title, "status": r["p"].status,
                             "currency": r["p"].currency, "budget": _f(r["fin"]["budget"]), "spent": _f(r["fin"]["spent"]),
                             "utilization": r["fin"]["utilization"], "activities": r["acts"]["total"],
                             "completed": r["acts"]["by_status"].get("completed", 0)} for r in cons["projects"]]
        data["consolidated"] = {"budget": _f(cons["budget"]), "spent": _f(cons["spent"]),
                                "other_currency": cons["other_currency"],
                                "note": "Programme and linked projects together. Each payment is recorded once, so "
                                        "nothing is counted twice. Indicator figures include verified results "
                                        "reported on linked project indicators."}
    return data


# --- Excel ------------------------------------------------------------------------------------

def to_xlsx(data, title):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="0F6E66")
    cur = data["programme"]["currency"]

    def sheet(ws, headers, rows, money_cols=(), pct_cols=()):
        ws.append(headers)
        for c in ws[1]:
            c.font, c.fill = head, fill
        for r in rows:
            ws.append(safe_row(r))
        for i, h in enumerate(headers, 1):
            col = get_column_letter(i)
            ws.column_dimensions[col].width = max(12, min(60, len(str(h)) + 4))
            if i in money_cols:
                for cell in ws[col][1:]:
                    cell.number_format = '#,##0.00'
            if i in pct_cols:
                for cell in ws[col][1:]:
                    cell.number_format = '0.0"%"'
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Summary"
    p, per, fin = data["programme"], data["period"], data["finance"]
    rows = [("Report", title), (p.get("kind", "programme").capitalize(), f"{p['code']} — {p['title']}"), ("Status", p["status"]),
            ("Manager", p["manager"] or ""), ("Period", f"{per['start'] or '—'} to {per['end']}"),
            ("Currency", cur), ("", ""),
            ("Budget", fin["budget"]), ("Spent (to date)", fin["spent"]), ("Spent in period", fin["period_spent"]),
            ("Committed", fin["committed"]), ("Available", fin["available"]),
            ("Budget used %", round(fin["utilization"], 1) if fin["utilization"] is not None else None),
            ("Funding committed", fin["funding_committed"]), ("Funding received", fin["funding_received"]),
            ("", ""), ("Participants (female)", data["participants"]["female"]),
            ("Participants (male)", data["participants"]["male"]), ("Note", data["participants"]["note"]),
            *([("", ""), ("People reached (registered, counted once)", data["reach"]["total"]),
               ("  of whom female", data["reach"]["female"]), ("  of whom male", data["reach"]["male"]),
               ("  living with a disability", data["reach"]["disability"]), ("Note", data["reach"]["note"])]
              if data.get("reach") else []),
            ("Generated", data["generated"])]
    for r in rows:
        ws.append(safe_row(r))
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 70
    for cell in ws["A"]:
        cell.font = Font(bold=True)
    for cell in ws["B"]:
        if isinstance(cell.value, float):
            cell.number_format = '#,##0.00'
    for k, label in (("summary", "Executive summary"), ("achievements", "Key achievements"), ("challenges", "Challenges"),
                     ("lessons", "Lessons learned"), ("next_steps", "Next period")):
        if data["narrative"].get(k):
            ws.append(safe_row([label, data["narrative"][k]]))
            ws.cell(ws.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
            ws.cell(ws.max_row, 1).font = Font(bold=True)

    sheet(wb.create_sheet("Indicators"),
          ["Code", "Indicator", "Unit", "Baseline", "Overall target", "Target in period", "Result in period",
           "Result to date", "Achievement %"],
          [[i["code"], i["name"], i["unit"], i["baseline"], i["target"], i["period_target"], i["period_actual"],
            i["cumulative"], round(i["achievement"], 1) if i["achievement"] is not None else None]
           for i in data["indicators"]], pct_cols=(9,))
    sheet(wb.create_sheet("Activities"),
          ["Code", "Activity", "Status", "Progress %", "Planned start", "Planned end", "Female", "Male", "Reports"],
          [[a["code"], a["title"], a["status"], a["progress"], a["planned_start"], a["planned_end"], a["female"],
            a["male"], a["reports"]] for a in data["activities"]])
    sheet(wb.create_sheet("Budget"),
          ["Category", f"Budget ({cur})", f"Spent ({cur})", f"Committed ({cur})", f"Available ({cur})", "Used %"],
          [[c["category"], c["amount"], c["spent"], c["committed"], c["available"],
            round(c["utilization"], 1) if c["utilization"] is not None else None] for c in data["categories"]],
          money_cols=(2, 3, 4, 5), pct_cols=(6,))
    sheet(wb.create_sheet("Milestones"), ["Milestone", "Due", "Achieved"],
          [[m["title"], m["due"], m["achieved"] or ""] for m in data["milestones"]])
    if data.get("projects"):
        sheet(wb.create_sheet("Projects"),
              ["Code", "Project", "Status", "Currency", "Budget", "Spent", "Used %", "Activities", "Completed"],
              [[r["code"], r["title"], r["status"], r["currency"], r["budget"], r["spent"],
                round(r["utilization"], 1) if r["utilization"] is not None else None, r["activities"], r["completed"]]
               for r in data["projects"]] +
              [["", "Programme and projects combined", "", cur, data["consolidated"]["budget"],
                data["consolidated"]["spent"], None, None, None]],
              money_cols=(5, 6), pct_cols=(7,))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --- PDF --------------------------------------------------------------------------------------

def to_pdf(data, title, org_name):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def esc(s):
        return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=title, author=org_name)
    ss = getSampleStyleSheet()
    body, h1, h2, small = ss["BodyText"], ss["Title"], ss["Heading2"], ss["BodyText"].clone("small", fontSize=8, leading=10)
    cell = ss["BodyText"].clone("cell", fontSize=8, leading=10)
    cell_r = ss["BodyText"].clone("cell_r", fontSize=8, leading=10, alignment=2)
    p, per, fin, cur = data["programme"], data["period"], data["finance"], data["programme"]["currency"]
    brand = colors.HexColor("#0F6E66")

    def table(headers, rows, widths, text_cols=1):
        """Columns after the first ``text_cols`` hold figures and are right-aligned."""
        def st(i):
            return cell if i < text_cols else cell_r
        t = Table([[Paragraph(f"<b>{esc(h)}</b>", st(i)) for i, h in enumerate(headers)]] +
                  [[Paragraph(esc(c), st(i)) for i, c in enumerate(r)] for r in rows], colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E3F1EF")),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.8, brand),
                               ("GRID", (0, 1), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        return t

    def money(v):
        return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"

    def num(v):
        return f"{v:,.4g}" if isinstance(v, (int, float)) else "—"

    els = [Paragraph(esc(org_name), small), Paragraph(esc(title), h1),
           Paragraph(f"{esc(p['code'])} — {esc(p['title'])}", h2),
           Paragraph(f"Period: {esc(per['start'] or '—')} to {esc(per['end'])} · Status: {esc(p['status'])} · "
                     f"Manager: {esc(p['manager'] or '—')}", body), Spacer(1, 6)]
    for k, label in (("summary", "Executive summary"), ("achievements", "Key achievements"),
                     ("challenges", "Challenges"), ("lessons", "Lessons learned"), ("next_steps", "Plans for the next period")):
        if data["narrative"].get(k):
            els += [Paragraph(label, h2), Paragraph(esc(data["narrative"][k]).replace("\n", "<br/>"), body)]
    els += [Paragraph("Financial summary", h2),
            table(["Item", f"Amount ({cur})"], [
                ("Budget", money(fin["budget"])), ("Spent to date", money(fin["spent"])),
                ("Spent in this period", money(fin["period_spent"])), ("Committed", money(fin["committed"])),
                ("Available", money(fin["available"])),
                ("Budget used", f"{fin['utilization']:.1f}%" if fin["utilization"] is not None else "—"),
                ("Funding committed", money(fin["funding_committed"])), ("Funding received", money(fin["funding_received"]))],
                [90 * mm, 60 * mm]), Spacer(1, 4)]
    if data["categories"]:
        els += [table(["Category", "Budget", "Spent", "Available", "Used"],
                      [(c["category"], money(c["amount"]), money(c["spent"]), money(c["available"]),
                        f"{c['utilization']:.0f}%" if c["utilization"] is not None else "—") for c in data["categories"]],
                      [60 * mm, 30 * mm, 30 * mm, 30 * mm, 25 * mm])]
    els += [Paragraph("Indicator performance", h2)]
    if data["indicators"]:
        els += [table(["Indicator", "Baseline", "Target", "Period", "To date", "Achieved"],
                      [(f"{i['code']} {i['name']}".strip(), num(i["baseline"]), num(i["target"]), num(i["period_actual"]),
                        num(i["cumulative"]), f"{i['achievement']:.0f}%" if i["achievement"] is not None else "—")
                       for i in data["indicators"]], [70 * mm, 20 * mm, 20 * mm, 20 * mm, 22 * mm, 22 * mm])]
    else:
        els.append(Paragraph("No indicators defined.", body))
    if data.get("reach") and data["reach"]["total"]:
        rc = data["reach"]
        els += [Paragraph("People reached", h2),
                Paragraph(f"{rc['total']} registered people ({rc['female']} female, {rc['male']} male, "
                          f"{rc['disability']} living with a disability).", body), Paragraph(esc(rc["note"]), small)]
    els += [Paragraph("Activities", h2)]
    if data["activities"]:
        els += [table(["Activity", "Status", "Progress", "Female", "Male"],
                      [(f"{a['code']} {a['title']}".strip(), a["status"].replace("_", " "), f"{a['progress']}%",
                        a["female"], a["male"]) for a in data["activities"]],
                      [80 * mm, 28 * mm, 22 * mm, 22 * mm, 22 * mm], text_cols=2),
                Paragraph(esc(data["participants"]["note"]), small)]
    else:
        els.append(Paragraph("No activities in this period.", body))
    if data["milestones"]:
        els += [Paragraph("Milestones", h2),
                table(["Milestone", "Due", "Achieved"], [(m["title"], m["due"], m["achieved"] or "Not yet")
                                                          for m in data["milestones"]], [100 * mm, 35 * mm, 35 * mm], text_cols=3)]
    if data.get("projects"):
        els += [Paragraph("Projects in this programme", h2),
                table(["Project", "Status", f"Budget ({cur})", f"Spent ({cur})", "Used"],
                      [(f"{r['code']} {r['title']}", r["status"].replace("_", " "),
                        money(r["budget"]) + ("" if r["currency"] == cur else f" {r['currency']}"),
                        money(r["spent"]), f"{r['utilization']:.0f}%" if r["utilization"] is not None else "—")
                       for r in data["projects"]] +
                      [("Programme and projects combined", "", money(data["consolidated"]["budget"]),
                        money(data["consolidated"]["spent"]), "")],
                      [78 * mm, 24 * mm, 30 * mm, 30 * mm, 14 * mm], text_cols=2),
                Paragraph(esc(data["consolidated"]["note"]), small)]
    els += [Spacer(1, 10), Paragraph(f"Generated by OIMS on {esc(data['generated'])}.", small)]
    doc.build(els)
    return buf.getvalue()

