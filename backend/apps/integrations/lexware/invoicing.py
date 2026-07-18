"""Send a local invoice draft to Lexware, and mirror the result.

The 504 hazard (lexware.md §6.4) is handled here: the invoice POST is
non-idempotent, so on timeout we park the invoice in ``send_pending`` and do NOT
retry — a reconciliation step (future) matches it against the voucherlist. On
success we store the link and mirror the returned fields.
"""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from apps.core.logging import get_logger
from apps.integrations.base import ProviderHTTPError
from apps.integrations.lexware.client import LexwareClient
from apps.integrations.lexware.mapping import apply_lexware_invoice, invoice_to_lexware_payload
from apps.integrations.models import ExternalObjectLink, Provider
from apps.invoicing.models import Invoice, InvoiceStatus

logger = get_logger("integrations.lexware.invoicing")


def send_invoice_to_lexware(invoice: Invoice) -> Invoice:
    """POST a draft to Lexware and mirror the result onto the local invoice.

    Respects ``LEXWARE_CREATE_FINAL_INVOICES`` (default false → creates a draft).
    Raises on API error; the caller turns that into a 502.
    """
    existing_link = ExternalObjectLink.objects.filter(
        workspace=invoice.workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        local_object_id=invoice.pk,
    ).first()
    if existing_link is not None:
        # The voucher already exists remotely (e.g. a retry after a timeout
        # that actually succeeded): reconcile instead of creating a duplicate.
        with LexwareClient() as reconcile_client:
            full = reconcile_client.get_invoice(existing_link.external_id)
        apply_lexware_invoice(invoice, full)
        invoice.last_synced_at = timezone.now()
        invoice.save()
        if invoice.status in (InvoiceStatus.OPEN, InvoiceStatus.PAID):
            from apps.invoicing.services import mark_entries_billed

            mark_entries_billed(invoice)
        logger.info("lexware_invoice_reconciled", invoice_id=str(invoice.pk))
        return invoice

    payload = invoice_to_lexware_payload(invoice)
    finalize = settings.LEXWARE_CREATE_FINAL_INVOICES

    invoice.status = InvoiceStatus.SEND_PENDING
    invoice.save(update_fields=["status", "updated_at"])

    client = LexwareClient()
    try:
        result = client.create_invoice(payload, finalize=finalize)
    except ProviderHTTPError as exc:
        # A definitive 4xx means Lexware REJECTED the payload — nothing was
        # created, so the draft goes back to fully editable instead of
        # sticking in "Übertragung läuft" forever. Only ambiguous outcomes
        # (timeout, 5xx — the voucher may exist remotely) stay send_pending.
        if exc.status_code is not None and 400 <= exc.status_code < 500:
            invoice.status = InvoiceStatus.DRAFT_LOCAL
            invoice.save(update_fields=["status", "updated_at"])
        logger.warning(
            "lexware_invoice_send_failed",
            invoice_id=str(invoice.pk),
            status_code=exc.status_code,
        )
        raise
    except Exception:
        # Non-HTTP failure (connection?): outcome unknown → keep send_pending.
        logger.warning("lexware_invoice_send_failed", invoice_id=str(invoice.pk))
        raise
    finally:
        client.close()

    external_id = result.get("id")
    if not external_id:
        raise RuntimeError("Lexware lieferte keine Rechnungs-ID zurück.")

    ExternalObjectLink.objects.update_or_create(
        workspace=invoice.workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        external_id=external_id,
        defaults={
            "local_object_type": "invoicing.Invoice",
            "local_object_id": invoice.pk,
            "external_version": str(result.get("version", "")),
            "last_synced_at": timezone.now(),
        },
    )

    # The create response is thin (id, version, dates); a follow-up GET returns
    # the full voucher we can mirror. Fetch it, but tolerate its absence.
    try:
        full = LexwareClient().get_invoice(external_id)
        apply_lexware_invoice(invoice, full)
    except Exception:
        invoice.status = InvoiceStatus.OPEN if finalize else InvoiceStatus.DRAFT_REMOTE
        invoice.lexware_version = result.get("version")

    invoice.last_synced_at = timezone.now()
    invoice.save()

    # Draft entries stay 'invoice_draft_created' until the invoice is finalised
    # and paid; a finalised (open) invoice marks them billed.
    if invoice.status == InvoiceStatus.OPEN:
        from apps.invoicing.services import mark_entries_billed

        mark_entries_billed(invoice)

    logger.info(
        "lexware_invoice_sent",
        invoice_id=str(invoice.pk),
        external_id=external_id,
        finalized=finalize,
    )
    return invoice
