"""GDPR export and erasure — including the § 147 AO legal hold."""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.core.audit import AuditLogEntry
from apps.crm.models import Client, ClientActivity, ClientContact, ClientNote
from apps.invoicing.services import compose_invoice
from apps.invoicing.tests.test_invoicing import make_entry
from apps.timetracking.models import TimeEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def full_client(workspace: Workspace, user: User) -> Client:
    client = Client.objects.create(
        workspace=workspace,
        name="Datenreich GmbH",
        email="kontakt@datenreich.example",
        phone="+49 30 1234567",
        billing_street="Musterstraße 1",
        billing_zip="10115",
        billing_city="Berlin",
        vat_id="DE123456789",
        default_hourly_rate=Decimal("100.00"),
        tags=["wichtig"],
    )
    ClientContact.objects.create(
        workspace=workspace,
        client=client,
        first_name="Petra",
        last_name="Person",
        email="petra@datenreich.example",
    )
    ClientNote.objects.create(
        workspace=workspace, client=client, author=user, content="Vertrauliche Notiz"
    )
    return client


class TestExport:
    def test_export_bundle_contains_all_domains(
        self, auth_client: APIClient, workspace: Workspace, user: User, full_client: Client
    ) -> None:
        entry = make_entry(workspace, user, full_client, hours=2)
        compose_invoice(
            workspace=workspace,
            client=full_client,
            entry_ids=[str(entry.pk)],
            grouping="lump_sum",
        )

        response = auth_client.get(reverse("client-export", args=[full_client.pk]))
        assert response.status_code == 200
        assert "attachment" in response["Content-Disposition"]

        bundle = response.data
        assert bundle["client"]["name"] == "Datenreich GmbH"
        assert bundle["contacts"][0]["first_name"] == "Petra"
        assert bundle["notes"][0]["content"] == "Vertrauliche Notiz"
        assert len(bundle["time_entries"]) == 1
        assert len(bundle["invoices"]) == 1
        assert "Art. 15 DSGVO" in bundle["export_note"]

        assert AuditLogEntry.objects.filter(action="privacy.client_exported").exists()

    def test_export_requires_admin(self, member_client: APIClient, full_client: Client) -> None:
        response = member_client.get(reverse("client-export", args=[full_client.pk]))
        assert response.status_code == 403


class TestErasure:
    def test_erase_without_business_records_hard_deletes(
        self, auth_client: APIClient, full_client: Client
    ) -> None:
        response = auth_client.post(
            reverse("client-erase", args=[full_client.pk]),
            {"confirm": "Datenreich GmbH"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["mode"] == "deleted"
        assert not Client.objects.filter(pk=full_client.pk).exists()
        assert AuditLogEntry.objects.filter(action="privacy.client_deleted").exists()

    def test_erase_with_invoices_anonymizes_under_legal_hold(
        self, auth_client: APIClient, workspace: Workspace, user: User, full_client: Client
    ) -> None:
        entry = make_entry(workspace, user, full_client, hours=2)
        invoice = compose_invoice(
            workspace=workspace,
            client=full_client,
            entry_ids=[str(entry.pk)],
            grouping="lump_sum",
        )

        response = auth_client.post(
            reverse("client-erase", args=[full_client.pk]),
            {"confirm": "Datenreich GmbH"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["mode"] == "anonymized"
        assert "§ 147 AO" in response.data["legal_basis"]

        full_client.refresh_from_db()
        # Personal data gone…
        assert full_client.name.startswith("Gelöschter Kunde")
        assert full_client.email == ""
        assert full_client.phone == ""
        assert full_client.billing_street == ""
        assert full_client.vat_id == ""
        assert full_client.tags == []
        assert full_client.archived is True
        assert not full_client.contacts.exists()
        assert not full_client.client_notes.exists()
        assert not ClientActivity.objects.filter(client=full_client).exists()
        # …business records intact (legal hold).
        invoice.refresh_from_db()
        assert invoice.client_id == full_client.pk
        assert TimeEntry.objects.filter(client=full_client, pk=entry.pk).exists()

        audit = AuditLogEntry.objects.get(action="privacy.client_erased")
        assert audit.summary == "Datenreich GmbH"

    def test_wrong_confirmation_is_rejected(
        self, auth_client: APIClient, full_client: Client
    ) -> None:
        response = auth_client.post(
            reverse("client-erase", args=[full_client.pk]),
            {"confirm": "falscher name"},
            format="json",
        )
        assert response.status_code == 400
        assert Client.objects.filter(pk=full_client.pk).exists()

    def test_erase_requires_admin(self, member_client: APIClient, full_client: Client) -> None:
        response = member_client.post(
            reverse("client-erase", args=[full_client.pk]),
            {"confirm": "Datenreich GmbH"},
            format="json",
        )
        assert response.status_code == 403
