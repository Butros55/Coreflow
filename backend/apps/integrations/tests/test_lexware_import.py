"""Full Lexware import: contacts become clients, invoices become mirrors —
correctly linked, idempotent, and triggered through the confirmed UI action."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Workspace
from apps.core.audit import AuditLogEntry
from apps.crm.models import Client
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.lexware.client import LexwareClient
from apps.integrations.lexware.sync import LexwareImport
from apps.integrations.models import ExternalObjectLink, Provider, ProviderProfile
from apps.invoicing.models import Invoice, InvoiceStatus

pytestmark = pytest.mark.django_db

LEXWARE = "https://api.lexware.io"


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


@pytest.fixture(autouse=True)
def _lexware_on() -> object:
    with override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key"):
        yield


def spring_page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"content": items, "last": True, "totalElements": len(items), "number": 0}


def contact(external_id: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": external_id,
        "version": 1,
        "roles": {"customer": {"number": 10001}},
        "company": {"name": "Import AG"},
        "addresses": {
            "billing": [
                {
                    "street": "Hafenstraße 5",
                    "zip": "20457",
                    "city": "Hamburg",
                    "countryCode": "DE",
                }
            ]
        },
        "emailAddresses": {"business": ["mail@import.example"]},
        "phoneNumbers": {"business": ["+49 40 123456"]},
        "archived": False,
    }
    data.update(overrides)
    return data


def remote_invoice(external_id: str, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": external_id,
        "voucherStatus": "paid",
        "voucherNumber": "RE-1001",
        "voucherDate": "2026-05-12T00:00:00.000+02:00",
        "version": 3,
        "address": {"contactId": "lex-contact-1", "name": "Import AG"},
        "lineItems": [
            {
                "type": "custom",
                "name": "Entwicklung",
                "description": "Sprint 4",
                "quantity": 10,
                "unitName": "Std.",
                "unitPrice": {
                    "currency": "EUR",
                    "netAmount": 95.0,
                    "taxRatePercentage": 19,
                },
            },
            {"type": "text", "name": "Hinweis", "description": "nur Text"},
        ],
        "totalPrice": {
            "currency": "EUR",
            "totalNetAmount": 950.0,
            "totalTaxAmount": 180.5,
            "totalGrossAmount": 1130.5,
        },
        "taxConditions": {"taxType": "net"},
        "paymentConditions": {"paymentTermDuration": 14},
        "title": "Rechnung",
    }
    data.update(overrides)
    return data


class TestContactImport:
    @respx.mock
    def test_company_contact_becomes_client_with_master_data(self, workspace: Workspace) -> None:
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([contact("lex-contact-1")]))
        )
        with LexwareClient() as conn:
            job = LexwareImport(workspace).import_contacts(conn)

        client = Client.objects.get(workspace=workspace, name="Import AG")
        assert client.client_number == "10001"
        assert client.email == "mail@import.example"
        assert client.billing_city == "Hamburg"
        assert ExternalObjectLink.objects.filter(
            resource_type="contact", external_id="lex-contact-1", local_object_id=client.pk
        ).exists()
        assert job.records_created == 1

    @respx.mock
    def test_person_contact_and_vendor_only_contact(self, workspace: Workspace) -> None:
        person = contact(
            "lex-contact-2",
            company=None,
            person={"firstName": "Petra", "lastName": "Einzeln"},
            roles={"customer": {"number": 10002}},
        )
        vendor = contact("lex-contact-3", roles={"vendor": {}})
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([person, vendor]))
        )
        with LexwareClient() as conn:
            job = LexwareImport(workspace).import_contacts(conn)

        assert Client.objects.filter(workspace=workspace, name="Petra Einzeln").exists()
        assert Client.objects.count() == 1  # vendor skipped
        assert job.records_skipped == 1

    @respx.mock
    def test_name_match_links_existing_client_without_duplicate(self, workspace: Workspace) -> None:
        existing = Client.objects.create(workspace=workspace, name="Import AG", email="alt@x.de")
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([contact("lex-contact-1")]))
        )
        with LexwareClient() as conn:
            LexwareImport(workspace).import_contacts(conn)

        assert Client.objects.filter(workspace=workspace).count() == 1
        existing.refresh_from_db()
        assert existing.email == "alt@x.de"  # local CRM data never overwritten
        link = ExternalObjectLink.objects.get(resource_type="contact")
        assert link.local_object_id == existing.pk

    @respx.mock
    def test_second_run_is_idempotent(self, workspace: Workspace) -> None:
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([contact("lex-contact-1")]))
        )
        with LexwareClient() as conn:
            LexwareImport(workspace).import_contacts(conn)
            job2 = LexwareImport(workspace).import_contacts(conn)

        assert Client.objects.count() == 1
        assert job2.records_created == 0


class TestInvoiceImport:
    def _mock_contact_and_lists(self, invoices: list[dict[str, Any]]) -> None:
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([contact("lex-contact-1")]))
        )
        respx.get(f"{LEXWARE}/v1/voucherlist").mock(
            return_value=httpx.Response(
                200,
                json=spring_page([{"id": inv["id"], "voucherType": "invoice"} for inv in invoices]),
            )
        )
        for inv in invoices:
            respx.get(f"{LEXWARE}/v1/invoices/{inv['id']}").mock(
                return_value=httpx.Response(200, json=inv)
            )
            respx.get(f"{LEXWARE}/v1/payments/{inv['id']}").mock(
                return_value=httpx.Response(
                    200,
                    json={"paymentStatus": "balanced", "openAmount": 0, "paidDate": "2026-05-20"},
                )
            )

    @respx.mock
    def test_paid_invoice_is_mirrored_and_attached_to_the_client(
        self, workspace: Workspace
    ) -> None:
        self._mock_contact_and_lists([remote_invoice("lex-inv-1")])
        with LexwareClient() as conn:
            importer = LexwareImport(workspace)
            importer.import_contacts(conn)
            job = importer.import_invoices(conn)

        invoice = Invoice.objects.get(workspace=workspace)
        assert invoice.client.name == "Import AG"  # linked via contactId
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.invoice_number == "RE-1001"
        assert invoice.net_amount == Decimal("950.00")
        assert invoice.gross_amount == Decimal("1130.50")
        assert invoice.invoice_date is not None
        assert invoice.is_editable is False  # a mirror, not a local draft

        lines = list(invoice.lines.all())
        assert len(lines) == 1  # text line skipped
        assert lines[0].title == "Entwicklung"
        assert lines[0].quantity == Decimal("10")
        assert lines[0].unit_price == Decimal("95.00")
        assert job.records_created == 1

    @respx.mock
    def test_already_linked_invoice_is_skipped_without_fetching(self, workspace: Workspace) -> None:
        """Invoices we created ourselves must never be re-imported."""
        existing_client = Client.objects.create(workspace=workspace, name="Import AG")
        local = Invoice.objects.create(
            workspace=workspace, client=existing_client, status=InvoiceStatus.DRAFT_REMOTE
        )
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="invoice",
            external_id="lex-inv-1",
            local_object_type="invoicing.Invoice",
            local_object_id=local.pk,
        )
        respx.get(f"{LEXWARE}/v1/voucherlist").mock(
            return_value=httpx.Response(
                200, json=spring_page([{"id": "lex-inv-1", "voucherType": "invoice"}])
            )
        )
        detail_route = respx.get(f"{LEXWARE}/v1/invoices/lex-inv-1").mock(
            return_value=httpx.Response(200, json=remote_invoice("lex-inv-1"))
        )
        with LexwareClient() as conn:
            job = LexwareImport(workspace).import_invoices(conn)

        assert Invoice.objects.count() == 1
        assert not detail_route.called
        assert job.records_skipped == 1

    @respx.mock
    def test_one_time_address_creates_a_minimal_client(self, workspace: Workspace) -> None:
        inv = remote_invoice(
            "lex-inv-2",
            voucherStatus="draft",
            address={"name": "Laufkundschaft GmbH", "countryCode": "DE", "city": "Kiel"},
        )
        respx.get(f"{LEXWARE}/v1/voucherlist").mock(
            return_value=httpx.Response(
                200, json=spring_page([{"id": "lex-inv-2", "voucherType": "invoice"}])
            )
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-inv-2").mock(
            return_value=httpx.Response(200, json=inv)
        )
        with LexwareClient() as conn:
            LexwareImport(workspace).import_invoices(conn)

        client = Client.objects.get(workspace=workspace, name="Laufkundschaft GmbH")
        invoice = Invoice.objects.get(workspace=workspace)
        assert invoice.client == client
        assert invoice.status == InvoiceStatus.DRAFT_REMOTE  # remote draft, not editable here


class TestImportTrigger:
    @respx.mock
    def test_full_flag_runs_the_import_and_audits_the_mode(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        ProviderProfile.objects.create(workspace=workspace, provider=Provider.LEXWARE)
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([contact("lex-contact-1")]))
        )
        respx.get(f"{LEXWARE}/v1/voucherlist").mock(
            return_value=httpx.Response(200, json=spring_page([]))
        )

        response = auth_client.post(
            reverse("integrations:sync", args=["lexware"]), {"full": True}, format="json"
        )
        assert response.status_code == 202
        # Eager Celery ran it inline: the contact landed as a client.
        assert Client.objects.filter(workspace=workspace, name="Import AG").exists()

        audit = AuditLogEntry.objects.get(action="integration.sync_triggered")
        assert audit.metadata["mode"] == "full_import"

    def test_search_window_guard_refuses_loudly(self, workspace: Workspace) -> None:
        importer = LexwareImport(workspace)
        with pytest.raises(RuntimeError, match="Suchfenster"):
            importer._iter_spring_pages(
                lambda p: {"content": [], "last": True, "totalElements": 20_000}
            )
