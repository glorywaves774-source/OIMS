"""CSV, Excel and PDF versions of an organization report (see app/analytics.py)."""
import csv
import io
from decimal import Decimal

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value):
    """Text that starts like a formula is prefixed with ' so spreadsheets show it instead of running it."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def fmt_value(v, fmt):
    """Human-readable text for screens and PDFs."""
    if v is None or v == "":
        return "—"
    if fmt == "money":
        return f"{Decimal(v):,.2f}"
    if fmt == "pct":
        return f"{float(v):.0f}%"
    if fmt == "int":
        return f"{int(v):,}"
    if fmt == "num":
        s = f"{float(v):,.2f}".rstrip("0").rstrip(".")
        return s or "0"
    if fmt == "date":
        return v.strftime("%d %b %Y") if hasattr(v, "strftime") else str(v)
    return str(v)


def fmt_compact(v, fmt):
    """Short labels for chart marks and axes (8.6K, 356K, 4.2M); full values stay in tooltips and tables."""
    if v is None:
        return "—"
    if fmt == "pct":
        return f"{float(v):.0f}%"
    x = float(v)
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= size:
            return f"{x / size:.1f}".rstrip("0").rstrip(".") + suffix
    return f"{x:,.0f}" if x == int(x) else f"{x:,.1f}"


def _cell(v, fmt):
    """Machine-readable value for CSV / Excel (numbers stay numbers)."""
    if v is None:
        return None
    if fmt in ("money", "num"):
        return float(v)
    if fmt == "int":
        return int(v)
    if fmt == "pct":
        return round(float(v), 1)
    if fmt == "date":
        return v.isoformat() if hasattr(v, "isoformat") else v
    return safe_text(str(v))


def to_csv(data, table_key=None):
    t = next((t for t in data["tables"] if t["key"] == table_key), data["tables"][0] if data["tables"] else None)
    buf = io.StringIO()
    w = csv.writer(buf)
    if t is None:
        w.writerow(["No data"])
        return buf.getvalue()
    w.writerow([safe_text(lbl) + (" (%)" if fmt == "pct" else "") for _, lbl, fmt in t["columns"]])
    for r in t["rows"] + ([t["total"]] if t.get("total") else []):
        w.writerow(["" if (v := _cell(r.get(k), fmt)) is None else v for k, _, fmt in t["columns"]])
    return "﻿" + buf.getvalue()   # BOM so Excel opens accented names correctly


def to_xlsx(data):
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append([safe_text(data["title"])])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([safe_text(data["organization"])])
    ws.append([safe_text(data["filters"])])
    ws.append([f"Generated {data['generated']}"])
    ws.append([])
    for s in data["summary"]:
        ws.append([safe_text(s["label"]), _cell(s["value"], s["fmt"])])
        if s["fmt"] == "money":
            ws.cell(ws.max_row, 2).number_format = "#,##0.00"
    if data["notes"]:
        ws.append([])
        for n in data["notes"]:
            ws.append([safe_text(n)])
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 48, 20
    used = set()
    for t in data["tables"]:
        name = "".join(ch for ch in t["title"] if ch not in "[]:*?/\\")[:31] or "Table"
        while name in used:
            name = name[:28] + f"_{len(used)}"
        used.add(name)
        sh = wb.create_sheet(name)
        sh.append([safe_text(lbl) + (" (%)" if fmt == "pct" else "") for _, lbl, fmt in t["columns"]])
        for c in sh[1]:
            c.font = Font(bold=True)
        for r in t["rows"] + ([t["total"]] if t.get("total") else []):
            sh.append([_cell(r.get(k), fmt) for k, _, fmt in t["columns"]])
        if t.get("total"):
            for c in sh[sh.max_row]:
                c.font = Font(bold=True)
        for i, (_, lbl, fmt) in enumerate(t["columns"], 1):
            col = sh.cell(1, i).column_letter
            sh.column_dimensions[col].width = max(10, min(45, len(lbl) + 4))
            if fmt == "money":
                for row in sh.iter_rows(min_row=2, min_col=i, max_col=i):
                    row[0].number_format = "#,##0.00"
        sh.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(data):
    from reportlab.graphics.shapes import Drawing, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    from xml.sax.saxutils import escape

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=data["title"])
    ss = getSampleStyleSheet()
    h1, h2, body, small = ss["Title"], ss["Heading2"], ss["BodyText"], ss["BodyText"].clone("small", fontSize=8, leading=10)
    cell = ss["BodyText"].clone("cell", fontSize=8, leading=10)
    teal = colors.HexColor("#0b8f80")
    width = landscape(A4)[0] - 28 * mm
    els = [Paragraph(escape(data["title"]), h1),
           Paragraph(escape(f"{data['organization']} · {data['filters']}"), body), Spacer(1, 6)]
    if data["summary"]:
        cells = [[Paragraph(f"<b>{escape(fmt_value(s['value'], s['fmt']))}</b><br/>{escape(s['label'])}", cell)
                  for s in data["summary"]]]
        t = Table(cells, colWidths=[width / len(data["summary"])] * len(data["summary"]))
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cfd8d6")),
                               ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cfd8d6")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        els += [t, Spacer(1, 8)]
    for ch in data["charts"]:
        rows = ch["rows"][:15]
        if not rows:
            continue
        els.append(Paragraph(escape(ch["title"]), h2))
        top = max((float(v) for _, v in rows), default=0) or 1
        if ch["kind"] == "bars":
            row_h, label_w, h = 14, 70 * mm, len(rows) * 14 + 4
            d = Drawing(width, h)
            for i, (lbl, v) in enumerate(rows):
                y = h - (i + 1) * row_h
                d.add(String(0, y + 3, str(lbl)[:48], fontSize=8))
                w = max(1.0, (width - label_w - 60) * float(v) / top)
                d.add(Rect(label_w, y + 2, w, 9, fillColor=teal, strokeColor=None))
                d.add(String(label_w + w + 4, y + 3, fmt_value(v, ch["fmt"]), fontSize=8))
        else:
            h, base = 110, 14
            d = Drawing(width, h)
            n = len(rows)
            slot = width / max(n, 1)
            bw = min(18, slot * 0.6)
            for i, (lbl, v) in enumerate(rows):
                x = i * slot + (slot - bw) / 2
                bh = (h - base - 16) * float(v) / top
                d.add(Rect(x, base, bw, max(bh, 0.5), fillColor=teal, strokeColor=None))
                d.add(String(x, 2, str(lbl)[:8], fontSize=7))
                if float(v) == top or i == n - 1:
                    d.add(String(x, base + bh + 3, fmt_value(v, ch["fmt"]), fontSize=7))
        els += [d, Spacer(1, 6)]
    for t in data["tables"]:
        els.append(Paragraph(escape(t["title"]), h2))
        if not t["rows"]:
            els.append(Paragraph("Nothing to show.", body))
            continue
        head = [Paragraph(f"<b>{escape(lbl)}</b>", cell) for _, lbl, _ in t["columns"]]
        body_rows = [[Paragraph(escape(fmt_value(r.get(k), fmt)), cell) for k, _, fmt in t["columns"]]
                     for r in t["rows"] + ([t["total"]] if t.get("total") else [])]
        tb = Table([head] + body_rows, repeatRows=1, colWidths=[width / len(t["columns"])] * len(t["columns"]))
        style = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cfd8d6")),
                 ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef3f2")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        for i, (_, _, fmt) in enumerate(t["columns"]):
            if fmt in ("money", "int", "num", "pct"):
                style.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
        tb.setStyle(TableStyle(style))
        els += [tb, Spacer(1, 8)]
    for n in data["notes"]:
        els.append(Paragraph(escape(n), small))
    els.append(Paragraph(f"Generated by OIMS on {escape(data['generated'])}.", small))
    doc.build(els)
    return buf.getvalue()


def safe_row(values):
    """A spreadsheet row with formula-like text neutralised (see safe_text)."""
    return [safe_text(v) for v in values]
