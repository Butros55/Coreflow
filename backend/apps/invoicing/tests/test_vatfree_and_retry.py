"""Regressions from real-world Lexware testing.

The user connected a real Kleinunternehmer account, switched a composed draft
to vatfree, and hit "Line items in vatfree invoices must not contain taxes" —
then the draft stuck in "Übertragung läuft" forever. Three layers broke:

1. Switching an invoice to vatfree left the LINES on their old tax rate.
2. The Lexware payload trusted the stored line rates.
3. A definitive 4xx rejection left the invoice in SEND_PENDING with no way
   to retry, edit, or cancel.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.lexware.mapping import invoice_to_lexware_payload
from apps.integrations.models import ExternalObjectLink, Provider
from apps.invoicing.models import Invoice, InvoiceStatus, TaxType
from apps.invoicing.services import compose_invoice
from apps.invoicing.tests.test_invoicing import make_entry
from apps.timetracking.models import BillingStatus, TimeEntry

pytestmark = pytest.mark.django_db

LEXWARE = "https://api.lexware.io"


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


@pytest.fixture
def client_record(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace, name="Acme GmbH", default_hourly_rate=Decimal("100.00")
    )


def _draft(workspace: Workspace, user: User, client_record: Client) -> Invoice:
    entry = make_entry(workspace, user, client_record, hours=2)
    return compose_invoice(
        workspace=workspace,
        client=client_record,
        entry_ids=[str(entry.pk)],
        grouping="per_service",
    )


class TestVatfreeLineRates:
    def test_switching_to_vatfree_zeroes_all_line_rates(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _draft(workspace, user, client_record)
        first_line = invoice.lines.first()
        assert first_line is not None
        assert first_line.tax_rate == Decimal("19.00")  # composed as net/19

        response = auth_client.patch(
            reverse("invoice-detail", args=[invoice.pk]),
            {"tax_type": "vatfree"},
            format="json",
        )
        assert response.status_code == 200

        invoice.refresh_from_db()
        assert invoice.tax_type == TaxType.VATFREE
        assert invoice.tax_rate == Decimal("0.00")
        assert set(invoice.lines.values_list("tax_rate", flat=True)) == {Decimal("0.00")}
        assert invoice.net_amount == invoice.gross_amount

    def test_switching_back_from_vatfree_restores_line_rates(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _draft(workspace, user, client_record)
        auth_client.patch(
            reverse("invoice-detail", args=[invoice.pk]), {"tax_type": "vatfree"}, format="json"
        )
        response = auth_client.patch(
            reverse("invoice-detail", args=[invoice.pk]), {"tax_type": "net"}, format="json"
        )
        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.tax_rate == Decimal("19.00")
        assert set(invoice.lines.values_list("tax_rate", flat=True)) == {Decimal("19.00")}

    def test_payload_forces_zero_rate_even_on_stale_lines(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        """Existing broken drafts (vatfree invoice, 19% lines) must still send
        a valid payload — the wire guard heals them without re-editing."""
        invoice = _draft(workspace, user, client_record)
        invoice.tax_type = TaxType.VATFREE
        invoice.tax_rate = Decimal("0.00")
        invoice.save()
        # Lines deliberately left stale at 19% — the historical bad state.
        assert set(invoice.lines.values_list("tax_rate", flat=True)) == {Decimal("19.00")}

        payload = invoice_to_lexware_payload(invoice)
        assert payload["taxConditions"]["taxType"] == "vatfree"
        rates = {item["unitPrice"]["taxRatePercentage"] for item in payload["lineItems"]}
        assert rates == {0}


class TestSendFailureAndRetry:
    @pytest.fixture(autouse=True)
    def _lexware_on(self) -> object:
        with override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key"):
            yield

    @respx.mock
    def test_definitive_rejection_returns_draft_to_editable(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _draft(workspace, user, client_record)
        respx.post(f"{LEXWARE}/v1/invoices").mock(
            return_value=httpx.Response(
                406,
                json={"message": "Line items in vatfree invoices must not contain taxes."},
            )
        )
        response = auth_client.post(reverse("invoice-send", args=[invoice.pk]), format="json")
        assert response.status_code == 502
        assert "vatfree" in response.data["error"]["message"]

        invoice.refresh_from_db()
        # NOT stuck in send_pending: the rejection was definitive.
        assert invoice.status == InvoiceStatus.DRAFT_LOCAL

    @respx.mock
    def test_stuck_send_pending_can_be_retried(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _draft(workspace, user, client_record)
        invoice.status = InvoiceStatus.SEND_PENDING  # historical stuck state
        invoice.save(update_fields=["status"])

        respx.post(f"{LEXWARE}/v1/invoices").mock(
            return_value=httpx.Response(201, json={"id": "lex-9", "version": 1})
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-9").mock(
            return_value=httpx.Response(
                200, json={"id": "lex-9", "voucherStatus": "draft", "version": 1}
            )
        )
        response = auth_client.post(reverse("invoice-send", args=[invoice.pk]), format="json")
        assert response.status_code == 200
        assert response.data["status"] == InvoiceStatus.DRAFT_REMOTE

    @respx.mock
    def test_send_pending_with_link_reconciles_instead_of_duplicating(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        """A timeout AFTER remote creation: the retry must fetch, not re-POST."""
        invoice = _draft(workspace, user, client_record)
        invoice.status = InvoiceStatus.SEND_PENDING
        invoice.save(update_fields=["status"])
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="invoice",
            external_id="lex-42",
            local_object_type="invoicing.Invoice",
            local_object_id=invoice.pk,
        )
        create_route = respx.post(f"{LEXWARE}/v1/invoices").mock(
            return_value=httpx.Response(201, json={"id": "NEW", "version": 1})
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-42").mock(
            return_value=httpx.Response(
                200,
                json={"id": "lex-42", "voucherStatus": "draft", "version": 3},
            )
        )
        response = auth_client.post(reverse("invoice-send", args=[invoice.pk]), format="json")
        assert response.status_code == 200
        assert not create_route.called  # no duplicate voucher
        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.DRAFT_REMOTE
        assert invoice.lexware_version == 3

    def test_stuck_send_pending_can_be_cancelled(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _draft(workspace, user, client_record)
        ite = invoice.invoice_time_entries.first()
        assert ite is not None
        entry_id = ite.time_entry_id
        invoice.status = InvoiceStatus.SEND_PENDING
        invoice.save(update_fields=["status"])

        response = auth_client.delete(reverse("invoice-detail", args=[invoice.pk]))
        assert response.status_code == 204
        assert TimeEntry.objects.get(pk=entry_id).billing_status == BillingStatus.OPEN
