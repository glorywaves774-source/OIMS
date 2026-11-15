"""Invoice PDF (reportlab), using the copies of names and prices stored on the invoice."""
import io
from decimal import Decimal
from xml.sax.saxutils import escape


def invoice_pdf(inv, settings):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm,
                            bottomMargin=18 * mm, title=f"Invoice {inv.number}")
    ss = getSampleStyleSheet()
    body, small = ss["BodyText"], ss["BodyText"].clone("small", fontSize=8, leading=10)
    issuer, bill = inv.issuer or {}, inv.bill_to or {}

    def block(d, keys):
        return "<br/>".join(escape(str(d.get(k))) for k in keys if d.get(k))

    status = {"open": "Due", "paid": "PAID", "void": "VOID"}[inv.status]
    head = Table([[Paragraph(f"<b>{escape(issuer.get('name') or '')}</b><br/>" +
                             block(issuer, ("address", "email")) +
                             (f"<br/>TIN {escape(issuer['tax_id'])}" if issuer.get("tax_id") else ""), body),
                   Paragraph(f"<font size=16><b>INVOICE</b></font><br/>{escape(inv.number)}<br/>Issued "
                             f"{inv.issued_on:%d %b %Y}<br/>{status}"
                             f"{' ' + inv.due_on.strftime('%d %b %Y') if inv.status == 'open' else ''}", body)]],
                 colWidths=[110 * mm, 64 * mm])
    els = [head, Spacer(1, 10), Paragraph("<b>Bill to</b>", body),
           Paragraph(block(bill, ("name", "address", "country", "email")) +
                     (f"<br/>Reg. no. {escape(bill['registration_number'])}" if bill.get("registration_number") else ""),
                     body), Spacer(1, 10)]
    rows = [["Description", f"Amount ({inv.currency})"]]
    rows += [[Paragraph(escape(line["description"]), body), f"{Decimal(line['amount']):,.2f}"] for line in inv.lines]
    rows.append(["Subtotal", f"{inv.subtotal:,.2f}"])
    if inv.tax_label:
        rows.append([f"{inv.tax_label} ({inv.tax_rate:g}%)", f"{inv.tax_amount:,.2f}"])
    rows.append(["Total", f"{inv.total:,.2f}"])
    if inv.amount_paid:
        rows.append(["Paid", f"{inv.amount_paid:,.2f}"])
        rows.append(["Balance", f"{inv.balance:,.2f}"])
    t = Table(rows, colWidths=[134 * mm, 40 * mm])
    t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.black),
                           ("LINEABOVE", (0, len(inv.lines) + 1), (-1, len(inv.lines) + 1), 0.4, colors.grey),
                           ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    els += [t, Spacer(1, 12)]
    if inv.status == "void" and inv.void_reason:
        els.append(Paragraph(f"<b>Cancelled:</b> {escape(inv.void_reason)}", body))
    if inv.status == "open" and settings.bank_details:
        els += [Paragraph("<b>How to pay by transfer</b>", body),
                Paragraph(escape(settings.bank_details).replace("\n", "<br/>") +
                          f"<br/>Use <b>{escape(inv.number)}</b> as the payment reference.", body), Spacer(1, 8)]
    for p in inv.payments:
        if p.status == "succeeded":
            els.append(Paragraph(f"Payment {p.received_on:%d %b %Y}: {p.currency} {p.amount:,.2f} — "
                                 f"{escape(p.METHODS.get(p.method, p.method))}, ref. {escape(p.reference)}", small))
    if settings.invoice_footer:
        els += [Spacer(1, 10), Paragraph(escape(settings.invoice_footer).replace("\n", "<br/>"), small)]
    doc.build(els)
    return buf.getvalue()
