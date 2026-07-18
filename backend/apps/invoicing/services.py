"""Invoice composition: turn selected time entries into an editable draft.

Everything here is local — no provider call. That is deliberate: a draft can be
built, previewed and edited with Lexware disabled, and only *sent* later.

Double-billing protection is layered:
  1. Selection only accepts entries in status ``open``/``marked_for_invoice``.
  2. The whole build runs in a transaction with ``SELECT ... FOR UPDATE`` on the
     entries, so two concurrent builds cannot both grab the same entry.
  3. The partial unique index on ``InvoiceTimeEntry`` is the final backstop.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import transaction

from apps.core.money import money, seconds_to_hours
from apps.invoicing.models import (
    Invoice,
    InvoiceGrouping,
    InvoiceLine,
    InvoiceStatus,
    InvoiceTimeEntry,
    TaxType,
)
from apps.timetracking.models import BillingStatus, TimeEntry

if TYPE_CHECKING:
    from apps.accounts.models import Workspace
    from apps.crm.models import Client

# Entries in these statuses may be pulled onto a new invoice.
SELECTABLE_STATUSES = frozenset({BillingStatus.OPEN, BillingStatus.MARKED})


class InvoiceCompositionError(Exception):
    """Raised when a set of entries cannot be composed into an invoice."""


@dataclass
class _LineDraft:
    title: str
    description: str
    unit: str
    seconds: int
    entries: list[TimeEntry]

    def hours(self) -> Decimal:
        return seconds_to_hours(self.seconds)


def _group_key(entry: TimeEntry, grouping: str) -> tuple[str, str]:
    """Return (sort_key, display) for an entry under a grouping strategy."""
    if grouping == InvoiceGrouping.PER_ENTRY:
        return (str(entry.started_at), entry.description or "Leistung")
    if grouping == InvoiceGrouping.PER_DAY:
        day = entry.started_at.astimezone().date().isoformat()
        return (day, f"Leistungen am {entry.started_at.astimezone().strftime('%d.%m.%Y')}")
    if grouping == InvoiceGrouping.PER_SERVICE:
        name = entry.service_type.name if entry.service_type else "Leistung"
        return (name, name)
    if grouping == InvoiceGrouping.PER_PHASE:
        name = entry.phase.name if entry.phase else "Projektleistung"
        return (name, name)
    if grouping == InvoiceGrouping.PER_TASK:
        name = entry.task.title if entry.task else (entry.description or "Leistung")
        return (name, name)
    # LUMP_SUM
    return ("", "Projektleistungen")


def preview_lines(entries: Sequence[TimeEntry], grouping: str) -> list[_LineDraft]:
    """Build the line drafts for a set of entries without persisting anything."""
    buckets: dict[tuple[str, str], _LineDraft] = {}
    for entry in entries:
        key = _group_key(entry, grouping)
        draft = buckets.get(key)
        if draft is None:
            draft = _LineDraft(title=key[1], description="", unit="Std.", seconds=0, entries=[])
            buckets[key] = draft
        draft.seconds += entry.duration_seconds
        draft.entries.append(entry)

    # Stable, human-friendly ordering.
    return [buckets[key] for key in sorted(buckets)]


def _resolve_rate(entries: Sequence[TimeEntry]) -> Decimal:
    """A representative hourly rate for a line.

    Entries carry a snapshotted rate; within a line they are usually identical.
    When they differ we fall back to the weighted average so the line total
    still equals the sum of entry amounts (which is what actually gets billed).
    """
    rates = {entry.hourly_rate for entry in entries}
    if len(rates) == 1:
        return next(iter(rates))
    total_amount = sum((entry.computed_amount for entry in entries), Decimal("0.00"))
    total_seconds = sum(entry.duration_seconds for entry in entries)
    if total_seconds == 0:
        return next(iter(rates))
    hours = seconds_to_hours(total_seconds)
    return money(total_amount / hours) if hours else next(iter(rates))


@transaction.atomic
def compose_invoice(
    *,
    workspace: Workspace,
    client: Client,
    entry_ids: Iterable[str],
    grouping: str = InvoiceGrouping.PER_SERVICE,
    project_id: str | None = None,
    tax_type: str | None = None,
    tax_rate: Decimal | None = None,
    payment_term_days: int | None = None,
) -> Invoice:
    """Create a local-draft invoice from the given open time entries.

    Raises :class:`InvoiceCompositionError` if any entry is missing, belongs to
    another client, or is already billed.
    """
    entry_ids = list(entry_ids)
    if not entry_ids:
        raise InvoiceCompositionError("Keine Zeiteinträge ausgewählt.")

    # Lock the rows for the duration of the build so a concurrent compose cannot
    # grab the same entries; the partial index is the last-resort backstop.
    # of=("self",) locks only the time-entry rows — the nullable service/phase/
    # task joins from select_related cannot be locked (Postgres refuses FOR
    # UPDATE on the nullable side of an outer join).
    entries = list(
        TimeEntry.objects.select_for_update(of=("self",))
        .filter(workspace=workspace, pk__in=entry_ids)
        .select_related("service_type", "phase", "task")
    )
    found_ids = {str(entry.pk) for entry in entries}
    missing = set(map(str, entry_ids)) - found_ids
    if missing:
        raise InvoiceCompositionError("Ein oder mehrere Zeiteinträge wurden nicht gefunden.")

    for entry in entries:
        if entry.client_id != client.pk:
            raise InvoiceCompositionError("Alle Zeiteinträge müssen zum selben Kunden gehören.")
        if not entry.billable:
            raise InvoiceCompositionError(
                f"Eintrag vom {entry.started_at:%d.%m.%Y} ist nicht abrechenbar."
            )
        if entry.billing_status not in SELECTABLE_STATUSES:
            raise InvoiceCompositionError(
                f"Eintrag vom {entry.started_at:%d.%m.%Y} ist bereits abgerechnet oder nicht offen."
            )

    # Resolve tax defaults from the connected Lexware profile, never hardcoded.
    resolved_tax_type, resolved_tax_rate = _resolve_tax(workspace, tax_type, tax_rate)

    dates = [entry.started_at.astimezone().date() for entry in entries]
    invoice = Invoice.objects.create(
        workspace=workspace,
        client=client,
        project_id=project_id,
        status=InvoiceStatus.DRAFT_LOCAL,
        tax_type=resolved_tax_type,
        tax_rate=resolved_tax_rate,
        currency=client.currency or "EUR",
        grouping=grouping,
        period_start=min(dates),
        period_end=max(dates),
        payment_term_days=payment_term_days
        or client.payment_term_days
        or workspace.default_payment_term_days,
        title="Rechnung",
        introduction="Für die erbrachten Leistungen erlauben wir uns zu berechnen:",
    )

    for order, draft in enumerate(preview_lines(entries, grouping)):
        rate = _resolve_rate(draft.entries)
        hours = draft.hours()
        # Sum entry amounts rather than recomputing from rounded hours, so the
        # line total equals what was actually tracked to the cent.
        line_total = money(sum((e.computed_amount for e in draft.entries), Decimal("0.00")))
        line = InvoiceLine.objects.create(
            workspace=workspace,
            invoice=invoice,
            title=draft.title,
            description=_line_description(draft),
            quantity=hours,
            unit="Std.",
            unit_price=rate,
            tax_rate=resolved_tax_rate if resolved_tax_type != TaxType.VATFREE else Decimal("0.00"),
            total_price=line_total,
            order=order,
        )
        for entry in draft.entries:
            InvoiceTimeEntry.objects.create(
                workspace=workspace,
                invoice=invoice,
                invoice_line=line,
                time_entry=entry,
                duration_seconds_taken=entry.duration_seconds,
                amount_taken=entry.computed_amount,
            )
        # Mark the entries as reserved for this draft.
        TimeEntry.objects.filter(pk__in=[e.pk for e in draft.entries]).update(
            billing_status=BillingStatus.DRAFT_CREATED
        )

    invoice.recompute_totals()
    invoice.save(update_fields=["net_amount", "tax_amount", "gross_amount", "open_amount"])
    return invoice


def _line_description(draft: _LineDraft) -> str:
    """A short breakdown of the entries in a line, for the invoice PDF."""
    if len(draft.entries) == 1 and draft.entries[0].description:
        return draft.entries[0].description
    dated: dict[date, int] = defaultdict(int)
    for entry in draft.entries:
        dated[entry.started_at.astimezone().date()] += entry.duration_seconds
    parts = [
        f"{day:%d.%m.}: {seconds_to_hours(seconds)} Std." for day, seconds in sorted(dated.items())
    ]
    return " · ".join(parts)


def _resolve_tax(
    workspace: Workspace, tax_type: str | None, tax_rate: Decimal | None
) -> tuple[str, Decimal]:
    """Resolve the invoice tax type/rate.

    Priority: explicit override → connected Lexware profile → workspace
    small-business flag. Never a blind hardcode (see lexware.md §4.5).
    """
    from apps.integrations.models import Provider, ProviderProfile

    if tax_type is not None:
        rate = (
            tax_rate
            if tax_rate is not None
            else (Decimal("0.00") if tax_type == TaxType.VATFREE else Decimal("19.00"))
        )
        return tax_type, rate

    profile = ProviderProfile.objects.filter(workspace=workspace, provider=Provider.LEXWARE).first()
    if profile and profile.tax_type:
        resolved = profile.tax_type
        rate = Decimal("0.00") if resolved == TaxType.VATFREE else Decimal("19.00")
        return resolved, rate

    if workspace.small_business:
        return TaxType.VATFREE, Decimal("0.00")
    return TaxType.NET, Decimal("19.00")


@transaction.atomic
def cancel_invoice(invoice: Invoice) -> None:
    """Void a local/draft invoice and release its time entries back to ``open``."""
    if invoice.status not in (InvoiceStatus.DRAFT_LOCAL, InvoiceStatus.DRAFT_REMOTE):
        raise InvoiceCompositionError(
            "Nur Entwürfe können hier storniert werden. Finalisierte Rechnungen "
            "werden in Lexware storniert."
        )
    entry_ids = list(invoice.invoice_time_entries.values_list("time_entry_id", flat=True))
    TimeEntry.objects.filter(pk__in=entry_ids).update(billing_status=BillingStatus.OPEN)
    invoice.invoice_time_entries.update(invoice_cancelled=True)
    invoice.status = InvoiceStatus.VOIDED
    invoice.save(update_fields=["status", "updated_at"])


@transaction.atomic
def mark_entries_billed(invoice: Invoice) -> None:
    """Move an invoice's entries to ``billed`` — called once it is finalised.

    Entries that originated in Clockodo are mirrored there as ``billable=2``
    via a retried background task (clockodo.md §5.7) — after commit, so a
    provider outage can never roll back the local billing state.
    """
    entry_ids = list(invoice.invoice_time_entries.values_list("time_entry_id", flat=True))
    TimeEntry.objects.filter(pk__in=entry_ids).update(billing_status=BillingStatus.BILLED)

    from django.conf import settings

    if settings.CLOCKODO_ENABLED and entry_ids:
        from apps.integrations.clockodo.tasks import push_entries_billed

        workspace_id = str(invoice.workspace_id)
        ids = [str(pk) for pk in entry_ids]
        transaction.on_commit(lambda: push_entries_billed.delay(workspace_id, ids))
