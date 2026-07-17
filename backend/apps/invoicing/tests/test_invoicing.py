"""Invoice composition, grouping, and double-billing protection."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.invoicing.models import (
    Invoice,
    InvoiceStatus,
    InvoiceTimeEntry,
    TaxType,
)
from apps.invoicing.services import (
    InvoiceCompositionError,
    cancel_invoice,
    compose_invoice,
)
from apps.timetracking.models import BillingStatus, ServiceType, TimeEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_record(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace,
        name="Acme GmbH",
        default_hourly_rate=Decimal("100.00"),
        payment_term_days=14,
        currency="EUR",
    )


def make_entry(
    workspace: Workspace,
    user: User,
    client: Client,
    *,
    hours: float = 1.0,
    days_ago: int = 1,
    rate: str = "100.00",
    service: ServiceType | None = None,
    billing_status: str = BillingStatus.OPEN,
    billable: bool = True,
) -> TimeEntry:
    seconds = int(hours * 3600)
    started = timezone.now() - timedelta(days=days_ago)
    rate_dec = Decimal(rate)
    amount = Decimal(seconds) / Decimal(3600) * rate_dec
    return TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        service_type=service,
        started_at=started,
        ended_at=started + timedelta(seconds=seconds),
        duration_seconds=seconds,
        hourly_rate=rate_dec,
        computed_amount=amount.quantize(Decimal("0.01")),
        billable=billable,
        billing_status=billing_status,
    )


class TestCompose:
    def test_compose_creates_local_draft_and_reserves_entries(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record, hours=2)
        e2 = make_entry(workspace, user, client_record, hours=1.5)

        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id), str(e2.id)],
            grouping="lump_sum",
        )
        assert invoice.status == InvoiceStatus.DRAFT_LOCAL
        # 3.5h × 100 = 350.00 net; small business off ⇒ net + 19%.
        assert invoice.net_amount == Decimal("350.00")
        assert invoice.tax_amount == Decimal("66.50")
        assert invoice.gross_amount == Decimal("416.50")

        e1.refresh_from_db()
        e2.refresh_from_db()
        assert e1.billing_status == BillingStatus.DRAFT_CREATED
        assert e2.billing_status == BillingStatus.DRAFT_CREATED

    def test_grouping_per_service_makes_one_line_per_service(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        dev = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        consult = ServiceType.objects.create(workspace=workspace, name="Beratung")
        make_entry(workspace, user, client_record, hours=2, service=dev)
        make_entry(workspace, user, client_record, hours=1, service=dev)
        make_entry(workspace, user, client_record, hours=3, service=consult)

        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e.id) for e in TimeEntry.objects.all()],
            grouping="per_service",
        )
        lines = list(invoice.lines.order_by("title"))
        assert len(lines) == 2
        titles = {line.title for line in lines}
        assert titles == {"Entwicklung", "Beratung"}
        dev_line = next(line for line in lines if line.title == "Entwicklung")
        assert dev_line.quantity == Decimal("3.0000")  # 2h + 1h

    def test_line_total_equals_sum_of_entry_amounts(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        """The line total must match tracked amounts to the cent — not a recompute
        from rounded hours, which would drift."""
        # 37-minute entries at 95/h: each 58.58, not a round number.
        e1 = make_entry(workspace, user, client_record, hours=37 / 60, rate="95.00")
        e2 = make_entry(workspace, user, client_record, hours=37 / 60, rate="95.00")
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id), str(e2.id)],
            grouping="lump_sum",
        )
        line = invoice.lines.first()
        assert line is not None
        assert line.total_price == e1.computed_amount + e2.computed_amount

    def test_small_business_client_gets_vatfree(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        workspace.small_business = True
        workspace.save()
        e1 = make_entry(workspace, user, client_record, hours=1)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id)],
        )
        assert invoice.tax_type == TaxType.VATFREE
        assert invoice.tax_amount == Decimal("0.00")
        assert invoice.gross_amount == invoice.net_amount

    def test_explicit_tax_type_overrides_default(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record, hours=1)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id)],
            tax_type="vatfree",
        )
        assert invoice.tax_type == TaxType.VATFREE

    def test_cannot_compose_billed_entries(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        billed = make_entry(workspace, user, client_record, billing_status=BillingStatus.BILLED)
        with pytest.raises(InvoiceCompositionError, match="bereits abgerechnet"):
            compose_invoice(
                workspace=workspace,
                client=client_record,
                entry_ids=[str(billed.id)],
            )

    def test_cannot_mix_clients(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        other = Client.objects.create(workspace=workspace, name="Other GmbH")
        e1 = make_entry(workspace, user, client_record)
        e2 = make_entry(workspace, user, other)
        with pytest.raises(InvoiceCompositionError, match="selben Kunden"):
            compose_invoice(
                workspace=workspace,
                client=client_record,
                entry_ids=[str(e1.id), str(e2.id)],
            )

    def test_empty_selection_is_rejected(self, workspace: Workspace, client_record: Client) -> None:
        with pytest.raises(InvoiceCompositionError):
            compose_invoice(workspace=workspace, client=client_record, entry_ids=[])


class TestDoubleBillingProtection:
    def test_entry_cannot_be_on_two_active_invoices(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        """The partial unique index is the real guarantee — proven directly."""
        entry = make_entry(workspace, user, client_record)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(entry.id)],
        )
        line = invoice.lines.first()
        assert line is not None
        # A second link for the same entry on a non-cancelled invoice must fail.
        with pytest.raises(IntegrityError), transaction.atomic():
            InvoiceTimeEntry.objects.create(
                workspace=workspace,
                invoice=invoice,
                invoice_line=line,
                time_entry=entry,
                duration_seconds_taken=100,
                amount_taken=Decimal("1.00"),
                invoice_cancelled=False,
            )

    def test_composing_an_already_reserved_entry_fails(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        entry = make_entry(workspace, user, client_record)
        compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(entry.id)],
        )
        # Its status is now draft_created, so a second compose is refused.
        with pytest.raises(InvoiceCompositionError):
            compose_invoice(
                workspace=workspace,
                client=client_record,
                entry_ids=[str(entry.id)],
            )

    def test_cancel_releases_entries_and_frees_them_for_reinvoicing(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        entry = make_entry(workspace, user, client_record)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(entry.id)],
        )
        cancel_invoice(invoice)

        entry.refresh_from_db()
        invoice.refresh_from_db()
        assert entry.billing_status == BillingStatus.OPEN
        assert invoice.status == InvoiceStatus.VOIDED

        # The cancelled links no longer block a fresh invoice.
        reinvoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(entry.id)],
        )
        assert reinvoice.status == InvoiceStatus.DRAFT_LOCAL


class TestInvoiceAPI:
    def test_open_entries_endpoint_groups_by_client(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        make_entry(workspace, user, client_record, hours=2)
        make_entry(workspace, user, client_record, hours=1)

        response = auth_client.get(reverse("open-entry-list"))
        assert response.status_code == 200
        clients = response.data["clients"]
        assert len(clients) == 1
        assert clients[0]["client_name"] == "Acme GmbH"
        assert len(clients[0]["entries"]) == 2
        assert clients[0]["total_amount"] == "300.00"

    def test_compose_via_api(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record, hours=2)
        response = auth_client.post(
            reverse("invoice-list"),
            {"client": str(client_record.id), "entry_ids": [str(e1.id)], "grouping": "lump_sum"},
            format="json",
        )
        assert response.status_code == 201
        assert response.data["status"] == "draft_local"
        assert response.data["net_amount"] == "200.00"

    def test_preview_does_not_persist(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record, hours=2)
        response = auth_client.post(
            reverse("invoice-preview"),
            {"client": str(client_record.id), "entry_ids": [str(e1.id)], "grouping": "per_day"},
            format="json",
        )
        assert response.status_code == 200
        assert response.data["total"] == "200.00"
        assert Invoice.objects.count() == 0
        e1.refresh_from_db()
        assert e1.billing_status == BillingStatus.OPEN  # untouched

    def test_send_without_lexware_returns_clear_error(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id)],
        )
        response = auth_client.post(reverse("invoice-send", args=[invoice.id]))
        assert response.status_code == 409
        assert response.data["error"]["code"] == "integration_disabled"
        # The local draft is untouched and still usable.
        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.DRAFT_LOCAL

    def test_cancel_via_api_releases_entries(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id)],
        )
        response = auth_client.delete(reverse("invoice-detail", args=[invoice.id]))
        assert response.status_code == 204
        e1.refresh_from_db()
        assert e1.billing_status == BillingStatus.OPEN

    def test_edit_draft_recomputes_totals(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        e1 = make_entry(workspace, user, client_record, hours=2)
        invoice = compose_invoice(
            workspace=workspace,
            client=client_record,
            entry_ids=[str(e1.id)],
            grouping="lump_sum",
        )
        line = invoice.lines.first()
        assert line is not None
        response = auth_client.patch(
            reverse("invoice-detail", args=[invoice.id]),
            {
                "title": "Angepasste Rechnung",
                "lines": [
                    {
                        "id": str(line.id),
                        "title": "Beratungsleistung",
                        "quantity": "3.00",
                        "unit": "Std.",
                        "unit_price": "120.00",
                        "tax_rate": "19.00",
                    }
                ],
            },
            format="json",
        )
        assert response.status_code == 200
        assert response.data["title"] == "Angepasste Rechnung"
        assert response.data["net_amount"] == "360.00"  # 3 × 120

    def test_foreign_workspace_invoice_is_404(
        self, auth_client: APIClient, other_workspace: Workspace, user: User
    ) -> None:
        foreign_client = Client.objects.create(workspace=other_workspace, name="Fremd")
        foreign_entry = make_entry(other_workspace, user, foreign_client)
        foreign_invoice = compose_invoice(
            workspace=other_workspace,
            client=foreign_client,
            entry_ids=[str(foreign_entry.id)],
        )
        response = auth_client.get(reverse("invoice-detail", args=[foreign_invoice.id]))
        assert response.status_code == 404
