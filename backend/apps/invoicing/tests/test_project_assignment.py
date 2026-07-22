"""Assigning invoices to projects: the quick-assign workflow."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.invoicing.models import Invoice, InvoiceLine, InvoiceStatus, InvoiceTimeEntry
from apps.projects.models import Project
from apps.timetracking.models import BillingStatus, TimeEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_record(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace,
        name="Acme GmbH",
        default_hourly_rate=Decimal("100.00"),
        currency="EUR",
    )


@pytest.fixture
def other_client(workspace: Workspace) -> Client:
    return Client.objects.create(workspace=workspace, name="Beta AG", currency="EUR")


@pytest.fixture
def project(workspace: Workspace, client_record: Client) -> Project:
    return Project.objects.create(workspace=workspace, client=client_record, name="Website")


def make_invoice(
    workspace: Workspace,
    client: Client,
    *,
    status: str = InvoiceStatus.OPEN,
    project: Project | None = None,
) -> Invoice:
    return Invoice.objects.create(
        workspace=workspace, client=client, status=status, project=project
    )


class TestAssignProject:
    def test_assigns_project_to_sent_invoice(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        client_record: Client,
        project: Project,
    ) -> None:
        # OPEN on purpose: assignment must work beyond local drafts.
        invoice = make_invoice(workspace, client_record, status=InvoiceStatus.OPEN)

        response = auth_client.post(
            f"/api/v1/invoices/{invoice.pk}/assign-project/",
            {"project": str(project.pk)},
            format="json",
        )
        assert response.status_code == 200, response.content
        assert response.data["project"] == project.pk
        assert response.data["project_name"] == "Website"

        invoice.refresh_from_db()
        assert invoice.project_id == project.pk

    def test_clearing_the_assignment(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        client_record: Client,
        project: Project,
    ) -> None:
        invoice = make_invoice(workspace, client_record, project=project)

        response = auth_client.post(
            f"/api/v1/invoices/{invoice.pk}/assign-project/",
            {"project": None},
            format="json",
        )
        assert response.status_code == 200
        invoice.refresh_from_db()
        assert invoice.project_id is None

    def test_rejects_project_of_a_different_client(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        other_client: Client,
        project: Project,
    ) -> None:
        invoice = make_invoice(workspace, other_client)

        response = auth_client.post(
            f"/api/v1/invoices/{invoice.pk}/assign-project/",
            {"project": str(project.pk)},
            format="json",
        )
        assert response.status_code == 409
        assert response.data["error"]["code"] == "client_mismatch"
        invoice.refresh_from_db()
        assert invoice.project_id is None

    def test_unknown_project_is_404(
        self, auth_client: APIClient, workspace: Workspace, client_record: Client
    ) -> None:
        invoice = make_invoice(workspace, client_record)
        response = auth_client.post(
            f"/api/v1/invoices/{invoice.pk}/assign-project/",
            {"project": "00000000-0000-0000-0000-000000000000"},
            format="json",
        )
        assert response.status_code == 404


def make_billed_entry(
    workspace: Workspace, user: User, client: Client, invoice: Invoice
) -> TimeEntry:
    """A time entry billed on the invoice (as the Lexware import produces)."""
    started = timezone.now() - timedelta(days=2)
    entry = TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        started_at=started,
        ended_at=started + timedelta(hours=2),
        duration_seconds=7200,
        hourly_rate=Decimal("100.00"),
        computed_amount=Decimal("200.00"),
        billable=True,
        billing_status=BillingStatus.BILLED,
    )
    line = InvoiceLine.objects.create(
        workspace=workspace,
        invoice=invoice,
        title="Beratung",
        quantity=Decimal("2"),
        unit_price=Decimal("100.00"),
        total_price=Decimal("200.00"),
    )
    InvoiceTimeEntry.objects.create(
        workspace=workspace,
        invoice_line=line,
        invoice=invoice,
        time_entry=entry,
        duration_seconds_taken=7200,
        amount_taken=Decimal("200.00"),
    )
    return entry


class TestEntriesFollowAssignment:
    def test_assigning_moves_linked_time_entries_into_the_project(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        user: User,
        client_record: Client,
        project: Project,
    ) -> None:
        invoice = make_invoice(workspace, client_record, status=InvoiceStatus.PAID)
        entry = make_billed_entry(workspace, user, client_record, invoice)
        assert entry.project_id is None

        response = auth_client.post(
            f"/api/v1/invoices/{invoice.pk}/assign-project/",
            {"project": str(project.pk)},
            format="json",
        )
        assert response.status_code == 200, response.content

        entry.refresh_from_db()
        assert entry.project_id == project.pk

    def test_clearing_releases_only_entries_of_that_project(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        user: User,
        client_record: Client,
        project: Project,
    ) -> None:
        other_project = Project.objects.create(
            workspace=workspace, client=client_record, name="Zweitprojekt"
        )
        invoice = make_invoice(workspace, client_record, project=project)
        moved = make_billed_entry(workspace, user, client_record, invoice)
        manual = make_billed_entry(workspace, user, client_record, invoice)
        TimeEntry.objects.filter(pk=moved.pk).update(project=project)
        # Manually tracked on another project — clearing must not touch it.
        TimeEntry.objects.filter(pk=manual.pk).update(project=other_project)

        response = auth_client.post(
            f"/api/v1/invoices/{invoice.pk}/assign-project/",
            {"project": None},
            format="json",
        )
        assert response.status_code == 200

        moved.refresh_from_db()
        manual.refresh_from_db()
        assert moved.project_id is None
        assert manual.project_id == other_project.pk


class TestLexwareDeeplinkAndDraftPdf:
    def test_detail_exposes_permalink_and_pdf_fails_fast_for_drafts(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        client_record: Client,
    ) -> None:
        from apps.integrations.models import ExternalObjectLink, Provider

        invoice = make_invoice(workspace, client_record, status=InvoiceStatus.DRAFT_REMOTE)
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="invoice",
            local_object_id=invoice.pk,
            external_id="ee220c84-0cc8-4847-94bf-3e52d3e4b770",
        )

        detail = auth_client.get(f"/api/v1/invoices/{invoice.pk}/")
        assert detail.status_code == 200
        assert detail.data["lexware_url"] == (
            "https://app.lexware.de/permalink/invoices/edit/ee220c84-0cc8-4847-94bf-3e52d3e4b770"
        )

        # The PDF endpoint refuses drafts locally, without calling Lexware.
        pdf = auth_client.get(f"/api/v1/invoices/{invoice.pk}/pdf/")
        assert pdf.status_code == 409
        assert pdf.data["error"]["code"] == "draft_has_no_pdf"

    def test_finalised_invoice_gets_view_permalink(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        client_record: Client,
    ) -> None:
        from apps.integrations.models import ExternalObjectLink, Provider

        invoice = make_invoice(workspace, client_record, status=InvoiceStatus.PAID)
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="invoice",
            local_object_id=invoice.pk,
            external_id="abc",
        )
        detail = auth_client.get(f"/api/v1/invoices/{invoice.pk}/")
        assert detail.data["lexware_url"] == "https://app.lexware.de/permalink/invoices/view/abc"

    def test_without_link_url_is_null(
        self, auth_client: APIClient, workspace: Workspace, client_record: Client
    ) -> None:
        invoice = make_invoice(workspace, client_record, status=InvoiceStatus.DRAFT_LOCAL)
        detail = auth_client.get(f"/api/v1/invoices/{invoice.pk}/")
        assert detail.data["lexware_url"] is None


class TestUnassignedFilter:
    def test_unassigned_returns_only_projectless_invoices(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        client_record: Client,
        project: Project,
    ) -> None:
        unassigned = make_invoice(workspace, client_record)
        make_invoice(workspace, client_record, project=project)

        response = auth_client.get("/api/v1/invoices/", {"unassigned": "true"})
        assert response.status_code == 200
        ids = [row["id"] for row in response.data["results"]]
        assert ids == [str(unassigned.pk)]

    def test_unassigned_combines_with_client_filter(
        self,
        auth_client: APIClient,
        workspace: Workspace,
        client_record: Client,
        other_client: Client,
    ) -> None:
        mine = make_invoice(workspace, client_record)
        make_invoice(workspace, other_client)

        response = auth_client.get(
            "/api/v1/invoices/", {"unassigned": "true", "client": str(client_record.pk)}
        )
        ids = [row["id"] for row in response.data["results"]]
        assert ids == [str(mine.pk)]
