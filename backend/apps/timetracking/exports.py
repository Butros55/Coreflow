"""CSV and PDF timesheet exports.

The API view owns filtering and workspace isolation.  This module only turns an
already-scoped sequence of completed entries into a portable document, which
keeps the security-sensitive queryset logic in one place and makes rendering
easy to test in isolation.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from typing import Any

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.accounts.models import Workspace
from apps.timetracking.models import TimeEntry

BILLING_LABELS = {
    "not_billable": "Nicht abrechenbar",
    "open": "Offen",
    "marked_for_invoice": "Vorgemerkt",
    "invoice_draft_created": "Rechnungsentwurf",
    "billed": "Abgerechnet",
    "cancelled": "Storniert",
}


def _local(value: Any) -> Any:
    return timezone.localtime(value) if timezone.is_aware(value) else value


def _hours(seconds: int) -> Decimal:
    return (Decimal(seconds) / Decimal(3600)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _decimal_de(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")


def render_timesheet_csv(entries: Sequence[TimeEntry]) -> bytes:
    """Return an Excel-friendly German CSV (UTF-8 BOM, semicolon delimiter)."""
    target = io.StringIO(newline="")
    writer = csv.writer(target, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "Datum",
            "Start",
            "Ende",
            "Kunde",
            "Projekt",
            "Aufgabe",
            "Leistungsart",
            "Beschreibung",
            "Dauer (h)",
            "Abrechenbar",
            "Stundensatz",
            "Betrag",
            "Abrechnungsstatus",
            "Benutzer",
        ]
    )
    for entry in entries:
        started = _local(entry.started_at)
        ended = _local(entry.ended_at) if entry.ended_at else None
        writer.writerow(
            [
                started.strftime("%d.%m.%Y"),
                started.strftime("%H:%M"),
                ended.strftime("%H:%M") if ended else "",
                entry.client.display_name,
                entry.project.name if entry.project else "",
                entry.task.title if entry.task else "",
                entry.service_type.name if entry.service_type else "",
                entry.description,
                _decimal_de(_hours(entry.duration_seconds)),
                "Ja" if entry.billable else "Nein",
                _decimal_de(entry.hourly_rate),
                _decimal_de(entry.computed_amount),
                BILLING_LABELS.get(entry.billing_status, entry.billing_status),
                entry.user.email,
            ]
        )
    # Excel recognises UTF-8 reliably when a BOM is present.
    return ("\ufeff" + target.getvalue()).encode("utf-8")


def render_timesheet_pdf(
    entries: Sequence[TimeEntry], *, workspace: Workspace, period_label: str
) -> bytes:
    """Render a compact landscape A4 timesheet with traceable totals."""
    target = io.BytesIO()
    document = SimpleDocTemplate(
        target,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=11 * mm,
        bottomMargin=11 * mm,
        title=f"Coreflow Tätigkeitsnachweis – {workspace.name}",
        author=workspace.name,
    )
    styles = getSampleStyleSheet()
    cell = ParagraphStyle(
        "TimesheetCell",
        parent=styles["BodyText"],
        fontName="Helvetica",
        fontSize=7.2,
        leading=9,
        textColor=colors.HexColor("#182033"),
    )
    cell_right = ParagraphStyle("TimesheetCellRight", parent=cell, alignment=TA_RIGHT)
    heading = ParagraphStyle(
        "TimesheetHeading",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=19,
        spaceAfter=3 * mm,
        textColor=colors.HexColor("#11182b"),
    )
    meta = ParagraphStyle(
        "TimesheetMeta",
        parent=styles["BodyText"],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#526078"),
    )

    story: list[Any] = [
        Paragraph("Tätigkeitsnachweis", heading),
        Paragraph(escape(workspace.legal_name or workspace.name), meta),
        Paragraph(escape(period_label), meta),
        Spacer(1, 4 * mm),
    ]

    header = [
        "Datum / Zeit",
        "Kunde / Projekt",
        "Aufgabe / Leistung",
        "Beschreibung",
        "Dauer",
        "Abrechnung",
        "Betrag",
    ]
    rows: list[list[Any]] = [header]
    total_seconds = 0
    total_amount = Decimal("0.00")
    for entry in entries:
        started = _local(entry.started_at)
        ended = _local(entry.ended_at) if entry.ended_at else None
        total_seconds += entry.duration_seconds
        if entry.billable:
            total_amount += entry.computed_amount
        time_text = (
            f"{started:%d.%m.%Y}<br/>{started:%H:%M}–{ended:%H:%M}"
            if ended
            else f"{started:%d.%m.%Y}<br/>{started:%H:%M}"
        )
        project_text = (
            f"<br/><font color='#64718a'>{escape(entry.project.name)}</font>"
            if entry.project
            else ""
        )
        service_text = (
            f"<br/><font color='#64718a'>{escape(entry.service_type.name)}</font>"
            if entry.service_type
            else ""
        )
        amount_text = (
            "—"
            if not entry.billable
            else f"{_decimal_de(entry.computed_amount)} {escape(workspace.default_currency)}"
        )
        rows.append(
            [
                Paragraph(time_text, cell),
                Paragraph(
                    escape(entry.client.display_name) + project_text,
                    cell,
                ),
                Paragraph(
                    escape(entry.task.title if entry.task else "—") + service_text,
                    cell,
                ),
                Paragraph(escape(entry.description or "—"), cell),
                Paragraph(f"{_decimal_de(_hours(entry.duration_seconds))} h", cell_right),
                Paragraph(
                    "Nicht abrechenbar"
                    if not entry.billable
                    else escape(BILLING_LABELS.get(entry.billing_status, entry.billing_status)),
                    cell,
                ),
                Paragraph(amount_text, cell_right),
            ]
        )

    total_label = ParagraphStyle("TotalLabel", parent=cell, fontName="Helvetica-Bold")
    rows.append(
        [
            "",
            "",
            "",
            Paragraph("Gesamt", total_label),
            Paragraph(f"{_decimal_de(_hours(total_seconds))} h", cell_right),
            "",
            Paragraph(
                f"{_decimal_de(total_amount)} {escape(workspace.default_currency)}",
                ParagraphStyle("TotalAmount", parent=cell_right, fontName="Helvetica-Bold"),
            ),
        ]
    )

    table = Table(
        rows,
        repeatRows=1,
        colWidths=[27 * mm, 42 * mm, 39 * mm, 64 * mm, 21 * mm, 35 * mm, 25 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222c49")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 7.5),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -2), 0.35, colors.HexColor("#cfd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#f6f8fb")]),
                ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#222c49")),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    document.build(story)
    return target.getvalue()
