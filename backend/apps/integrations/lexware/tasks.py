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

    Mirrors three kinds of remote change:
    * status/number/payment updates (an invoice that turns OPEN or PAID marks
      its entries billed — which pushes ``billable=2`` to Clockodo),
    * a voucher **voided** in Lexware → local VOIDED, hours released,
    * a draft **deleted** in Lexware (GET → 404) → local VOIDED, hours
      released. A 404 on a *finalised* invoice is anomalous (Lexware does not
      delete finalised vouchers) and becomes a SyncConflict instead of an
      automatic change — billed data is under legal hold.
    """
    from apps.core.audit import record_audit
    from apps.integrations.base import ProviderHTTPError
    from apps.integrations.lexware.client import LexwareClient
    from apps.integrations.lexware.mapping import apply_lexware_invoice
    from apps.invoicing.models import Invoice, InvoiceStatus
    from apps.invoicing.services import mark_entries_billed, release_invoice_entries

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
        status__in=[
            InvoiceStatus.DRAFT_REMOTE,
            InvoiceStatus.OPEN,
            InvoiceStatus.SEND_PENDING,
        ],
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

    updated = deleted_remotely = failed = 0
    with LexwareClient() as client:
        for invoice in invoices:
            job.records_processed += 1
            link = by_local_id[invoice.pk]
            was_billable_settled = invoice.status in {InvoiceStatus.OPEN, InvoiceStatus.PAID}
            was_voided = invoice.status == InvoiceStatus.VOIDED
            try:
                remote = client.get_invoice(link.external_id)
            except ProviderHTTPError as exc:
                if exc.status_code == 404:
                    _handle_remote_deletion(workspace, invoice, link, job)
                    deleted_remotely += 1
                else:
                    failed += 1
                    logger.warning(
                        "lexware_invoice_refresh_failed",
                        invoice_id=str(invoice.pk),
                        error=str(exc),
                    )
                continue
            except Exception as exc:
                failed += 1
                logger.warning(
                    "lexware_invoice_refresh_failed",
                    invoice_id=str(invoice.pk),
                    error=str(exc),
                )
                continue

            try:
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

            if invoice.status == InvoiceStatus.VOIDED and not was_voided:
                # Voided in Lexware (Stornorechnung): the hours are billable
                # again — mirror exactly what a local cancel does.
                release_invoice_entries(invoice)
                record_audit(
                    None,
                    "invoice.remote_voided",
                    workspace=workspace,
                    target=invoice,
                    summary=invoice.invoice_number or str(invoice.pk),
                )
            else:
                now_settled = invoice.status in {InvoiceStatus.OPEN, InvoiceStatus.PAID}
                if now_settled and not was_billable_settled:
                    mark_entries_billed(invoice)
            updated += 1

    job.records_updated = updated
    job.records_skipped = deleted_remotely
    job.records_failed = failed
    job.save()
    job.mark_finished(SyncStatus.SUCCESS if failed == 0 else SyncStatus.PARTIAL)
    return {"updated": updated, "deleted_remotely": deleted_remotely, "failed": failed}


def _handle_remote_deletion(workspace: Any, invoice: Any, link: Any, job: Any) -> None:
    """The linked voucher is gone from Lexware — mirror the user's action."""
    from apps.core.audit import record_audit
    from apps.integrations.models import SyncConflict
    from apps.invoicing.models import InvoiceStatus
    from apps.invoicing.services import release_invoice_entries

    link.deleted_remotely = True
    link.save(update_fields=["deleted_remotely", "updated_at"])

    if invoice.status in (InvoiceStatus.DRAFT_REMOTE, InvoiceStatus.SEND_PENDING):
        # A deleted draft is a normal user decision: void locally, free the
        # hours for re-billing, show "Storniert" in the UI.
        release_invoice_entries(invoice)
        record_audit(
            None,
            "invoice.remote_deleted",
            workspace=workspace,
            target=invoice,
            summary=invoice.invoice_number or str(invoice.pk),
        )
        logger.info("lexware_invoice_deleted_remotely", invoice_id=str(invoice.pk))
        return

    # Finalised invoice vanished: that should not happen — surface it, touch
    # nothing (legal hold on billed data).
    SyncConflict.objects.create(
        workspace=workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        external_id=link.external_id,
        local_object_type="invoicing.Invoice",
        local_object_id=invoice.pk,
        reason="remote_deleted",
        local_snapshot={
            "status": invoice.status,
            "invoice_number": invoice.invoice_number,
            "gross_amount": str(invoice.gross_amount),
        },
        remote_snapshot={},
        sync_job=job,
    )
    logger.warning("lexware_finalised_invoice_missing", invoice_id=str(invoice.pk))


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


@shared_task(name="apps.integrations.lexware.tasks.lexware_full_import")
def lexware_full_import(workspace_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Manual full import: all Lexware contacts + invoices into the local UI."""
    from apps.accounts.models import User, Workspace
    from apps.integrations.lexware.client import LexwareClient, is_lexware_enabled
    from apps.integrations.lexware.sync import LexwareImport

    if not is_lexware_enabled():
        return {"status": "disabled"}
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return {"status": "unknown_workspace"}
    user = User.objects.filter(pk=user_id).first() if user_id else None

    with LexwareClient() as client_conn:
        jobs = LexwareImport(workspace, trigger="manual", triggered_by=user).full_import(
            client_conn
        )
    return {"status": "ok", "jobs": {job.resource_type: job.status for job in jobs}}
