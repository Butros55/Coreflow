"""Full Lexware import: contacts become clients, invoices become mirrors —
correctly linked, idempotent, and triggered through the confirmed UI action."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.core.audit import AuditLogEntry
from apps.core.money import money
from apps.crm.models import Client
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.lexware.client import LexwareClient
from apps.integrations.lexware.sync import LexwareImport
from apps.integrations.models import ExternalObjectLink, Provider, ProviderProfile
from apps.invoicing.models import Invoice, InvoiceLinkSource, InvoiceStatus, InvoiceTimeEntry
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry

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


def mock_contact_and_lists(invoices: list[dict[str, Any]]) -> None:
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


class TestInvoiceImport:
    def _mock_contact_and_lists(self, invoices: list[dict[str, Any]]) -> None:
        mock_contact_and_lists(invoices)

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


def _time_entry(
    workspace: Workspace,
    user: User,
    client: Client,
    *,
    hours: float,
    day: str,
    service_type: ServiceType | None = None,
    description: str = "",
) -> TimeEntry:
    started = timezone.make_aware(dt.datetime.fromisoformat(f"{day}T09:00:00"))
    seconds = int(hours * 3600)
    return TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        service_type=service_type,
        description=description,
        started_at=started,
        ended_at=started + dt.timedelta(seconds=seconds),
        duration_seconds=seconds,
        source=EntrySource.MANUAL,
        billable=True,
        hourly_rate=Decimal("95.00"),
        computed_amount=money(Decimal(seconds) / 3600 * Decimal("95.00")),
        billing_status=BillingStatus.OPEN,
    )


SERVICE_PERIOD = {
    "shippingDate": "2026-05-01T00:00:00.000+02:00",
    "shippingEndDate": "2026-05-10T00:00:00.000+02:00",
    "shippingType": "serviceperiod",
}


def run_full_import(workspace: Workspace, invoices: list[dict[str, Any]]) -> None:
    mock_contact_and_lists(invoices)
    with LexwareClient() as conn:
        importer = LexwareImport(workspace)
        importer.import_contacts(conn)
        importer.import_invoices(conn)


class TestTimeEntryMatching:
    """Imported lines are matched to open entries — exactly or not at all."""

    def _run_import(self, workspace: Workspace, invoices: list[dict[str, Any]]) -> None:
        run_full_import(workspace, invoices)

    @respx.mock
    def test_service_line_matches_entries_and_marks_them_lexware_billed(
        self, workspace: Workspace, user: User
    ) -> None:
        service = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        client = Client.objects.create(workspace=workspace, name="Import AG")
        first = _time_entry(
            workspace, user, client, hours=6, day="2026-05-03", service_type=service
        )
        second = _time_entry(
            workspace, user, client, hours=4, day="2026-05-05", service_type=service
        )

        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )

        invoice = Invoice.objects.get(workspace=workspace)
        assert invoice.period_start == dt.date(2026, 5, 1)  # mirrored from shipping
        assert invoice.period_end == dt.date(2026, 5, 10)

        links = InvoiceTimeEntry.objects.filter(invoice=invoice)
        assert links.count() == 2
        assert {link.time_entry_id for link in links} == {first.pk, second.pk}
        assert all(link.source == InvoiceLinkSource.LEXWARE_IMPORT for link in links)
        assert all(link.invoice_line.title == "Entwicklung" for link in links)

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.billing_status == BillingStatus.BILLED  # invoice is paid
        assert second.billing_status == BillingStatus.BILLED

    @respx.mock
    def test_draft_invoice_reserves_entries_instead_of_billing(
        self, workspace: Workspace, user: User
    ) -> None:
        service = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        client = Client.objects.create(workspace=workspace, name="Import AG")
        entry = _time_entry(
            workspace, user, client, hours=10, day="2026-05-03", service_type=service
        )

        self._run_import(
            workspace,
            [remote_invoice("lex-inv-1", voucherStatus="draft", shippingConditions=SERVICE_PERIOD)],
        )

        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.DRAFT_CREATED
        link = InvoiceTimeEntry.objects.get(time_entry=entry)
        assert link.source == InvoiceLinkSource.LEXWARE_IMPORT

    @respx.mock
    def test_hours_mismatch_creates_no_links(self, workspace: Workspace, user: User) -> None:
        """8 tracked vs 10 billed: guessing which hours were billed is wrong."""
        service = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        client = Client.objects.create(workspace=workspace, name="Import AG")
        entry = _time_entry(
            workspace, user, client, hours=8, day="2026-05-03", service_type=service
        )

        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )

        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.OPEN
        assert InvoiceTimeEntry.objects.count() == 0

    @respx.mock
    def test_ambiguous_single_entry_match_is_skipped(
        self, workspace: Workspace, user: User
    ) -> None:
        """Two open 10h entries, line says 10h — either could be it, so neither is."""
        client = Client.objects.create(workspace=workspace, name="Import AG")
        _time_entry(workspace, user, client, hours=10, day="2026-05-03")
        _time_entry(workspace, user, client, hours=10, day="2026-05-05")

        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )

        assert InvoiceTimeEntry.objects.count() == 0
        assert not TimeEntry.objects.filter(billing_status=BillingStatus.BILLED).exists()

    @respx.mock
    def test_unambiguous_single_entry_matches_without_service_type(
        self, workspace: Workspace, user: User
    ) -> None:
        client = Client.objects.create(workspace=workspace, name="Import AG")
        entry = _time_entry(workspace, user, client, hours=10, day="2026-05-03")
        _time_entry(workspace, user, client, hours=3, day="2026-05-04")  # different hours

        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )

        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.BILLED
        assert InvoiceTimeEntry.objects.get().time_entry_id == entry.pk

    @respx.mock
    def test_entries_outside_service_period_stay_open(
        self, workspace: Workspace, user: User
    ) -> None:
        service = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        client = Client.objects.create(workspace=workspace, name="Import AG")
        entry = _time_entry(
            workspace, user, client, hours=10, day="2026-06-20", service_type=service
        )

        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )

        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.OPEN
        assert InvoiceTimeEntry.objects.count() == 0

    @respx.mock
    def test_rerun_matches_previously_imported_invoice(
        self, workspace: Workspace, user: User
    ) -> None:
        """Mirrors imported before the matcher existed get their entries later."""
        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )
        # No links yet: nothing tracked, and reconstruction has no active
        # member to own entries in this fixture setup.
        assert InvoiceTimeEntry.objects.count() == 0

        service = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        client = Client.objects.get(workspace=workspace, name="Import AG")
        entry = _time_entry(
            workspace, user, client, hours=10, day="2026-05-03", service_type=service
        )

        self._run_import(
            workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)]
        )

        assert Invoice.objects.count() == 1  # still no duplicate mirror
        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.BILLED
        assert InvoiceTimeEntry.objects.get().source == InvoiceLinkSource.LEXWARE_IMPORT

    @respx.mock
    def test_matched_entries_are_not_reused_for_a_second_line(
        self, workspace: Workspace, user: User
    ) -> None:
        dev = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        client = Client.objects.create(workspace=workspace, name="Import AG")
        dev_entry = _time_entry(
            workspace, user, client, hours=10, day="2026-05-03", service_type=dev
        )
        advice_entry = _time_entry(workspace, user, client, hours=10, day="2026-05-04")

        two_lines = remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)
        two_lines["lineItems"].insert(
            1,
            {
                "type": "custom",
                "name": "Beratung",
                "quantity": 10,
                "unitName": "Std.",
                "unitPrice": {"currency": "EUR", "netAmount": 95.0, "taxRatePercentage": 19},
            },
        )
        self._run_import(workspace, [two_lines])

        invoice = Invoice.objects.get(workspace=workspace)
        links = InvoiceTimeEntry.objects.filter(invoice=invoice).select_related("invoice_line")
        by_line = {link.invoice_line.title: link.time_entry_id for link in links}
        # "Entwicklung" took its service-type bucket; the 10h "Beratung" line
        # then found exactly one remaining 10h entry.
        assert by_line == {"Entwicklung": dev_entry.pk, "Beratung": advice_entry.pk}


class TestTimeEntryReconstruction:
    """No local hours at all → the invoice's hour lines become billed entries."""

    @respx.mock
    def test_hour_lines_become_billed_lexware_entries(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        inv = remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)
        inv["lineItems"].append(
            {
                "type": "custom",
                "name": "Lizenz",
                "quantity": 1,
                "unitName": "Stück",
                "unitPrice": {"currency": "EUR", "netAmount": 100.0, "taxRatePercentage": 19},
            }
        )
        run_full_import(workspace, [inv])

        entries = TimeEntry.objects.filter(workspace=workspace)
        assert entries.count() == 1  # text line and "Stück" line are not time
        entry = entries.get()
        assert entry.source == EntrySource.LEXWARE
        assert entry.billing_status == BillingStatus.BILLED
        assert entry.user == user  # owner of the workspace
        assert entry.duration_seconds == 36000  # 10 h
        assert entry.hourly_rate == Decimal("95.00")
        assert entry.computed_amount == Decimal("950.00")
        assert entry.service_type is not None and entry.service_type.name == "Entwicklung"
        assert "Sprint 4" in entry.description
        assert entry.started_at.date() == dt.date(2026, 5, 1)  # period start

        link = InvoiceTimeEntry.objects.get()
        assert link.source == InvoiceLinkSource.LEXWARE_IMPORT
        assert link.invoice_line.title == "Entwicklung"
        assert link.time_entry_id == entry.pk

    @respx.mock
    def test_reconstruction_is_idempotent_across_reruns(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        inv = remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)
        run_full_import(workspace, [inv])
        run_full_import(workspace, [inv])

        assert TimeEntry.objects.filter(workspace=workspace).count() == 1
        assert InvoiceTimeEntry.objects.count() == 1

    @respx.mock
    def test_draft_invoice_reconstructs_as_reserved(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        inv = remote_invoice("lex-inv-1", voucherStatus="draft", shippingConditions=SERVICE_PERIOD)
        run_full_import(workspace, [inv])

        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.billing_status == BillingStatus.DRAFT_CREATED
        assert entry.source == EntrySource.LEXWARE

    @respx.mock
    def test_without_active_member_reconstruction_is_skipped(self, workspace: Workspace) -> None:
        run_full_import(workspace, [remote_invoice("lex-inv-1", shippingConditions=SERVICE_PERIOD)])
        assert TimeEntry.objects.count() == 0
        assert Invoice.objects.count() == 1  # the mirror itself still lands


class TestContactMasterData:
    """Contact persons and tax ids ride along with the contact import."""

    @respx.mock
    def test_contact_persons_and_tax_ids_are_imported(self, workspace: Workspace) -> None:
        enriched = contact(
            "lex-contact-1",
            company={
                "name": "Import AG",
                "taxNumber": "5/123/45678",
                "vatRegistrationId": "DE123456789",
                "contactPersons": [
                    {
                        "firstName": "Petra",
                        "lastName": "Primär",
                        "primary": True,
                        "emailAddress": "petra@import.example",
                        "phoneNumber": "+49 40 111",
                    },
                    {"firstName": "Sven", "lastName": "Sekundär", "primary": False},
                ],
            },
        )
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([enriched]))
        )
        with LexwareClient() as conn:
            LexwareImport(workspace).import_contacts(conn)

        client = Client.objects.get(workspace=workspace, name="Import AG")
        assert client.tax_number == "5/123/45678"
        assert client.vat_id == "DE123456789"
        contacts = list(client.contacts.order_by("-is_primary", "last_name"))
        assert [(c.first_name, c.is_primary) for c in contacts] == [
            ("Petra", True),
            ("Sven", False),
        ]
        assert contacts[0].email == "petra@import.example"

    @respx.mock
    def test_rerun_backfills_empty_fields_without_overwriting(self, workspace: Workspace) -> None:
        plain = contact("lex-contact-1")
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([plain]))
        )
        with LexwareClient() as conn:
            LexwareImport(workspace).import_contacts(conn)

        client = Client.objects.get(workspace=workspace, name="Import AG")
        client.email = "lokal@firma.de"  # locally maintained — must survive
        client.save(update_fields=["email"])

        enriched = contact(
            "lex-contact-1",
            company={
                "name": "Import AG",
                "taxNumber": "5/123/45678",
                "contactPersons": [{"firstName": "Petra", "lastName": "Primär", "primary": True}],
            },
        )
        respx.get(f"{LEXWARE}/v1/contacts").mock(
            return_value=httpx.Response(200, json=spring_page([enriched]))
        )
        with LexwareClient() as conn:
            LexwareImport(workspace).import_contacts(conn)

        client.refresh_from_db()
        assert client.tax_number == "5/123/45678"  # empty field got filled
        assert client.email == "lokal@firma.de"  # local value untouched
        assert client.contacts.count() == 1


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
