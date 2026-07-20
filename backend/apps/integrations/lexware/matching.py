"""Attach open time entries to invoices imported from Lexware.

The full import mirrors historical invoices — but the hours they billed often
still sit in Coreflow as "open" (tracked locally or imported from Clockodo) and
would look unbilled forever. This module assigns invoice lines to those entries
after the mirror is created.

Matching is deliberately conservative: a link is only created when the hours
add up **exactly** (same client, inside the service period). Anything ambiguous
stays unmatched — a wrong link would silently swallow billable hours, a missing
link is visible and can be explained. Every created link carries
``source="lexware_import"`` so the UI can show where the assignment came from.

Strategies per line, in order (first non-empty bucket wins — if a named bucket
exists but its hours do not sum to the line quantity, the line stays unmatched
rather than falling through to a looser strategy):

1. **Leistungsart**: line title equals a service type name → all open entries
   of that service type.
2. **Tag**: line title matches the composer's per-day format
   ("Leistungen am 12.03.2026") → all open entries of that day.
3. **Beschreibung**: line title equals an entry description (the composer's
   per-entry format).
4. **Einzeleintrag**: exactly one open entry has exactly the line's hours.
5. **Gesamtsumme**: the invoice has exactly one hour line and *all* open
   entries in the period sum to it (the composer's lump-sum format).
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from apps.core.logging import get_logger
from apps.core.money import money, seconds_to_hours
from apps.invoicing.models import Invoice, InvoiceLinkSource, InvoiceStatus, InvoiceTimeEntry
from apps.invoicing.services import SELECTABLE_STATUSES, mark_entries_billed
from apps.timetracking.models import BillingStatus, TimeEntry

if TYPE_CHECKING:
    from apps.invoicing.models import InvoiceLine

logger = get_logger("integrations.lexware.matching")

# Mirrors of real Lexware vouchers. Local drafts manage their own links.
MATCHABLE_STATUSES = frozenset(
    {InvoiceStatus.DRAFT_REMOTE, InvoiceStatus.OPEN, InvoiceStatus.PAID, InvoiceStatus.OVERDUE}
)

# Units that mean "hours" — only such lines can correspond to time entries.
_HOUR_UNITS = {"std", "std.", "h", "stunde", "stunden", "stunde(n)", "hour", "hours"}

_DAY_TITLE = re.compile(r"^Leistungen am (\d{2}\.\d{2}\.\d{4})$")


def _is_hour_line(line: InvoiceLine) -> bool:
    return line.unit.strip().casefold() in _HOUR_UNITS and line.quantity > 0


def _hours_match(entries: list[TimeEntry], quantity: Decimal) -> bool:
    """Exact comparison at the line's 2-decimal precision.

    The composer stores ``sum(seconds) → hours`` rounded once into the 2-place
    quantity column, so the same rounding must be applied here.
    """
    total = seconds_to_hours(sum(entry.duration_seconds for entry in entries))
    return money(total) == money(quantity)


def _entry_day(entry: TimeEntry) -> dt.date:
    # astimezone() matches the composer's grouping convention exactly.
    return entry.started_at.astimezone().date()


def _bucket_for_line(line: InvoiceLine, pool: list[TimeEntry]) -> list[TimeEntry] | None:
    """Return the entries a line stands for, or None if undecidable."""
    title = line.title.strip().casefold()

    service_bucket = [
        e for e in pool if e.service_type and e.service_type.name.strip().casefold() == title
    ]
    if service_bucket:
        return service_bucket if _hours_match(service_bucket, line.quantity) else None

    day_match = _DAY_TITLE.match(line.title.strip())
    if day_match:
        day = dt.datetime.strptime(day_match.group(1), "%d.%m.%Y").date()
        day_bucket = [e for e in pool if _entry_day(e) == day]
        if day_bucket:
            return day_bucket if _hours_match(day_bucket, line.quantity) else None

    description_bucket = [e for e in pool if e.description.strip().casefold() == title]
    if description_bucket:
        return description_bucket if _hours_match(description_bucket, line.quantity) else None

    exact = [e for e in pool if _hours_match([e], line.quantity)]
    if len(exact) == 1:
        return exact
    return None


@transaction.atomic
def match_invoice_time_entries(invoice: Invoice) -> int:
    """Assign open time entries to an imported invoice's lines.

    Returns the number of entries linked. Idempotent: an invoice that already
    has active links, or entries that are no longer open, are never touched.
    """
    if invoice.status not in MATCHABLE_STATUSES:
        return 0
    if invoice.invoice_time_entries.filter(invoice_cancelled=False).exists():
        return 0

    period_start = invoice.period_start
    period_end = invoice.period_end
    if period_start is None and period_end is None and invoice.invoice_date is None:
        # No date anchor at all — any match would be a guess.
        return 0

    # Same locking discipline as the composer, so a concurrent compose and this
    # matcher cannot claim the same entries (the partial unique index backstops).
    candidates = [
        entry
        for entry in TimeEntry.objects.select_for_update(of=("self",))
        .filter(
            workspace=invoice.workspace,
            client=invoice.client,
            billable=True,
            billing_status__in=SELECTABLE_STATUSES,
            ended_at__isnull=False,
        )
        .select_related("service_type")
        if _in_period(entry, period_start, period_end, invoice.invoice_date)
    ]
    if not candidates:
        return 0

    hour_lines = [line for line in invoice.lines.all() if _is_hour_line(line)]
    pool = list(candidates)
    matched: list[tuple[InvoiceLine, list[TimeEntry]]] = []

    for line in hour_lines:
        bucket = _bucket_for_line(line, pool)
        if bucket is None and len(hour_lines) == 1 and _hours_match(pool, line.quantity):
            # Lump-sum invoice: one hour line covering the whole period.
            bucket = list(pool)
        if not bucket:
            continue
        matched.append((line, bucket))
        bucket_ids = {e.pk for e in bucket}
        pool = [e for e in pool if e.pk not in bucket_ids]

    if not matched:
        return 0

    for line, bucket in matched:
        for entry in bucket:
            InvoiceTimeEntry.objects.create(
                workspace=invoice.workspace,
                invoice=invoice,
                invoice_line=line,
                time_entry=entry,
                duration_seconds_taken=entry.duration_seconds,
                amount_taken=entry.computed_amount,
                source=InvoiceLinkSource.LEXWARE_IMPORT,
            )

    matched_ids = [entry.pk for _, bucket in matched for entry in bucket]
    if invoice.status == InvoiceStatus.DRAFT_REMOTE:
        TimeEntry.objects.filter(pk__in=matched_ids).update(
            billing_status=BillingStatus.DRAFT_CREATED
        )
    else:
        # Finalised in Lexware → billed here (also pushes billable=2 for
        # Clockodo-sourced entries, same as the local finalisation path).
        mark_entries_billed(invoice)

    logger.info(
        "lexware_time_entries_matched",
        invoice_id=str(invoice.pk),
        invoice_number=invoice.invoice_number,
        entries=len(matched_ids),
        lines=len(matched),
    )
    return len(matched_ids)


def _in_period(
    entry: TimeEntry,
    period_start: dt.date | None,
    period_end: dt.date | None,
    invoice_date: dt.date | None,
) -> bool:
    day = _entry_day(entry)
    if period_start is not None and period_end is not None:
        return period_start <= day <= period_end
    # Without a service period the voucher date is the only anchor: nothing
    # tracked after invoicing day can have been billed on it.
    anchor = period_end or invoice_date
    return anchor is not None and day <= anchor
