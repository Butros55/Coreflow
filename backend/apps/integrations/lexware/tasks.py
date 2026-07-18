"""Lexware background tasks: mirror maintenance for sent invoices.

Lexware owns invoice numbers, status and payments (docs/integrations/lexware.md
§1). This task refreshes the local mirror of every sent invoice so "Offen" and
"Bezahlt" on the dashboard track reality without a manual click.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.core.logging import get_logger
from apps.integrations.models import ExternalObjectLink, Provider, SyncJob, SyncStatus

logger = get_logger("integrations.lexware.tasks")


@shared_task(name="apps.integrations.lexware.tasks.sync_lexware_incremental")
def sync_lexware_incremental() -> dict[str, Any]:
    """Beat: refresh status + payments of non-final mirrored invoices."""
    from apps.integrations.lexware.client import is_lexware_enabled

    if not is_lexware_enabled():
        return {"status": "disabled"}

    from apps.accounts.models import Workspace

    results: dict[str, Any] = {}
    for workspace in Workspace.objects.filter(is_active=True):
        summary = sync_invoice_statuses(workspace)
        if summary:
            results[str(workspace.pk)] = summary
    return {"status": "ok", "workspaces": results}


def sync_invoice_statuses(workspace: Any) -> dict[str, int] | None:
    """Pull current voucher state for every linked, non-final invoice.

    Also settles the paperwork trail: an invoice that turns OPEN or PAID marks
    its time entries billed — which in turn pushes ``billable=2`` to Clockodo
    for entries that originated there.
    """
    from apps.integrations.lexware.client import LexwareClient
    from apps.integrations.lexware.mapping import apply_lexware_invoice
    from apps.invoicing.models import Invoice, InvoiceStatus
    from apps.invoicing.services import mark_entries_billed

    links = ExternalObjectLink.objects.filter(
        workspace=workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        deleted_remotely=False,
    )
    by_local_id = {link.local_object_id: link for link in links}
    if not by_local_id:
        return None

    invoices = Invoice.objects.filter(
        workspace=workspace,
        pk__in=by_local_id.keys(),
        status__in=[InvoiceStatus.DRAFT_REMOTE, InvoiceStatus.OPEN],
    )
    if not invoices.exists():
        return None

    job = SyncJob.objects.create(
        workspace=workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        direction="inbound",
        trigger="scheduled",
    )
    job.mark_running()

    updated = skipped = failed = 0
    with LexwareClient() as client:
        for invoice in invoices:
            job.records_processed += 1
            link = by_local_id[invoice.pk]
            was_billable_settled = invoice.status in {InvoiceStatus.OPEN, InvoiceStatus.PAID}
            try:
                remote = client.get_invoice(link.external_id)
                apply_lexware_invoice(invoice, remote)
                _apply_payment_state(client, invoice, link.external_id)
            except Exception as exc:
                failed += 1
                logger.warning(
                    "lexware_invoice_refresh_failed",
                    invoice_id=str(invoice.pk),
                    error=str(exc),
                )
                continue

            invoice.last_synced_at = timezone.now()
            invoice.save()
            link.mark_synced({"voucherStatus": invoice.status, "version": invoice.lexware_version})

            now_settled = invoice.status in {InvoiceStatus.OPEN, InvoiceStatus.PAID}
            if now_settled and not was_billable_settled:
                mark_entries_billed(invoice)
            updated += 1

    job.records_updated = updated
    job.records_skipped = skipped
    job.records_failed = failed
    job.save()
    job.mark_finished(SyncStatus.SUCCESS if failed == 0 else SyncStatus.PARTIAL)
    return {"updated": updated, "failed": failed}


def _apply_payment_state(client: Any, invoice: Any, external_id: str) -> None:
    """Mirror open amount / paid date. Drafts have no payment info (406 → None,
    lexware.md §4.8) and that is not an error."""
    payments = client.get_payments(external_id)
    if not payments:
        return
    open_amount = payments.get("openAmount")
    if open_amount is not None:
        try:
            # One doc sample shows a string, others a number — parse leniently.
            invoice.open_amount = Decimal(str(open_amount))
        except InvalidOperation:
            logger.warning("lexware_open_amount_unparseable", value=str(open_amount))
    paid_date = payments.get("paidDate")
    if paid_date:
        try:
            invoice.paid_at = dt.date.fromisoformat(str(paid_date)[:10])
        except ValueError:
            logger.warning("lexware_paid_date_unparseable", value=str(paid_date))
