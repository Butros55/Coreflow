"""Deletions and cancellations made directly in Lexware must reach the UI.

A draft deleted in Lexware (GET → 404) voids the local mirror and frees the
hours; a voucher voided in Lexware does the same via its status; a finalised
invoice that vanishes becomes a conflict — never an automatic change.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings

from apps.accounts.models import User, Workspace
from apps.core.audit import AuditLogEntry
from apps.crm.models import Client
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.lexware.tasks import sync_invoice_statuses
from apps.integrations.models import ExternalObjectLink, Provider, SyncConflict
from apps.invoicing.models import Invoice, InvoiceStatus
from apps.invoicing.services import compose_invoice
from apps.invoicing.tests.test_invoicing import make_entry
from apps.timetracking.models import BillingStatus, TimeEntry

pytestmark = pytest.mark.django_db

LEXWARE = "https://api.lexware.io"


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


@pytest.fixture(autouse=True)
def _lexware_on() -> object:
    with override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key"):
        yield


@pytest.fixture
def client_record(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace, name="Acme GmbH", default_hourly_rate=Decimal("100.00")
    )


def _linked_invoice(
    workspace: Workspace,
    user: User,
    client_record: Client,
    *,
    status: str,
    external_id: str = "lex-77",
) -> tuple[Invoice, str]:
    entry = make_entry(workspace, user, client_record, hours=2)
    invoice = compose_invoice(
        workspace=workspace,
        client=client_record,
        entry_ids=[str(entry.pk)],
        grouping="lump_sum",
    )
    invoice.status = status
    invoice.save(update_fields=["status"])
    if status in (InvoiceStatus.OPEN, InvoiceStatus.PAID):
        TimeEntry.objects.filter(pk=entry.pk).update(billing_status=BillingStatus.BILLED)
    ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        external_id=external_id,
        local_object_type="invoicing.Invoice",
        local_object_id=invoice.pk,
    )
    return invoice, str(entry.pk)


class TestRemoteDeletion:
    @respx.mock
    def test_deleted_draft_voids_locally_and_frees_the_hours(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice, entry_id = _linked_invoice(
            workspace, user, client_record, status=InvoiceStatus.DRAFT_REMOTE
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-77").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        summary = sync_invoice_statuses(workspace)
        assert summary is not None
        assert summary["deleted_remotely"] == 1
        assert summary["failed"] == 0

        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.VOIDED  # shows "Storniert" in the UI
        entry = TimeEntry.objects.get(pk=entry_id)
        assert entry.billing_status == BillingStatus.OPEN  # billable again

        link = ExternalObjectLink.objects.get(local_object_id=invoice.pk)
        assert link.deleted_remotely is True
        assert AuditLogEntry.objects.filter(action="invoice.remote_deleted").exists()

    @respx.mock
    def test_vanished_finalised_invoice_becomes_a_conflict(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice, entry_id = _linked_invoice(
            workspace, user, client_record, status=InvoiceStatus.OPEN
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-77").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )

        sync_invoice_statuses(workspace)

        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.OPEN  # untouched — legal hold
        assert TimeEntry.objects.get(pk=entry_id).billing_status == BillingStatus.BILLED

        conflict = SyncConflict.objects.get()
        assert conflict.reason == "remote_deleted"
        assert conflict.local_object_id == invoice.pk

    @respx.mock
    def test_remote_void_releases_the_entries(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice, entry_id = _linked_invoice(
            workspace, user, client_record, status=InvoiceStatus.OPEN
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-77").mock(
            return_value=httpx.Response(
                200,
                json={"id": "lex-77", "voucherStatus": "voided", "version": 4},
            )
        )
        respx.get(f"{LEXWARE}/v1/payments/lex-77").mock(
            return_value=httpx.Response(200, json={"paymentStatus": "balanced", "openAmount": 0})
        )

        sync_invoice_statuses(workspace)

        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.VOIDED
        assert TimeEntry.objects.get(pk=entry_id).billing_status == BillingStatus.OPEN
        assert invoice.invoice_time_entries.filter(invoice_cancelled=True).exists()
        assert AuditLogEntry.objects.filter(action="invoice.remote_voided").exists()

    @respx.mock
    def test_second_run_does_not_reprocess_the_deleted_link(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        _linked_invoice(workspace, user, client_record, status=InvoiceStatus.DRAFT_REMOTE)
        respx.get(f"{LEXWARE}/v1/invoices/lex-77").mock(
            return_value=httpx.Response(404, json={"message": "Not found"})
        )
        sync_invoice_statuses(workspace)
        # Link is now flagged deleted_remotely and the invoice is VOIDED —
        # the second run has nothing left to look at.
        assert sync_invoice_statuses(workspace) is None

    @respx.mock
    def test_stuck_send_pending_with_link_is_healed_by_the_beat(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice, _ = _linked_invoice(
            workspace, user, client_record, status=InvoiceStatus.SEND_PENDING
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-77").mock(
            return_value=httpx.Response(
                200, json={"id": "lex-77", "voucherStatus": "draft", "version": 2}
            )
        )
        respx.get(f"{LEXWARE}/v1/payments/lex-77").mock(
            return_value=httpx.Response(406, json={"message": "draft"})
        )

        sync_invoice_statuses(workspace)
        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.DRAFT_REMOTE
