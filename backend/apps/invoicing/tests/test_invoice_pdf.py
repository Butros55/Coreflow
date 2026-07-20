"""Invoice PDF: streamed from Lexware on demand — draft or final."""

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
from apps.integrations.models import ExternalObjectLink, Provider
from apps.invoicing.models import Invoice
from apps.invoicing.services import compose_invoice
from apps.invoicing.tests.test_invoicing import make_entry

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


def _invoice(workspace: Workspace, user: User, client_record: Client) -> Invoice:
    entry = make_entry(workspace, user, client_record, hours=1)
    return compose_invoice(
        workspace=workspace,
        client=client_record,
        entry_ids=[str(entry.pk)],
        grouping="lump_sum",
    )


def _link(workspace: Workspace, invoice: Invoice) -> None:
    ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.LEXWARE,
        resource_type="invoice",
        external_id="lex-pdf-1",
        local_object_type="invoicing.Invoice",
        local_object_id=invoice.pk,
    )


class TestInvoicePdf:
    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key")
    def test_streams_the_lexware_document(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _invoice(workspace, user, client_record)
        _link(workspace, invoice)
        respx.get(f"{LEXWARE}/v1/invoices/lex-pdf-1/file").mock(
            return_value=httpx.Response(
                200, content=b"%PDF-1.7 lexware", headers={"Content-Type": "application/pdf"}
            )
        )

        response = auth_client.get(reverse("invoice-pdf", args=[invoice.pk]))
        assert response.status_code == 200
        assert response.headers["Content-Type"] == "application/pdf"
        assert b"".join(response.streaming_content) == b"%PDF-1.7 lexware"  # type: ignore[attr-defined]

    def test_unsent_local_draft_has_no_pdf(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _invoice(workspace, user, client_record)
        response = auth_client.get(reverse("invoice-pdf", args=[invoice.pk]))
        assert response.status_code == 404
        assert response.data["error"]["code"] == "no_remote_document"

    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key")
    def test_lexware_406_becomes_a_friendly_message(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _invoice(workspace, user, client_record)
        _link(workspace, invoice)
        respx.get(f"{LEXWARE}/v1/invoices/lex-pdf-1/file").mock(
            return_value=httpx.Response(406, json={"message": "not renderable"})
        )
        response = auth_client.get(reverse("invoice-pdf", args=[invoice.pk]))
        assert response.status_code == 502
        assert "kein PDF" in response.data["error"]["message"]

    def test_disabled_integration_is_a_clear_409(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        invoice = _invoice(workspace, user, client_record)
        _link(workspace, invoice)
        response = auth_client.get(reverse("invoice-pdf", args=[invoice.pk]))
        assert response.status_code == 409
