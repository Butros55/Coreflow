"""The internal business report: series, rates, and per-entity aggregations."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.finance.services import business_report
from apps.invoicing.models import Invoice, InvoiceStatus
from apps.projects.models import Project
from apps.timetracking.models import BillingStatus, TimeEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_record(workspace: Workspace) -> Client:
    return Client.objects.create(workspace=workspace, name="Acme GmbH", currency="EUR")


def make_entry(
    workspace: Workspace,
    user: User,
    client: Client,
    *,
    hours: float,
    days_ago: int,
    billing_status: str = BillingStatus.BILLED,
    billable: bool = True,
    project: Project | None = None,
) -> TimeEntry:
    seconds = int(hours * 3600)
    started = timezone.now() - timedelta(days=days_ago)
    amount = Decimal(seconds) / Decimal(3600) * Decimal("100.00")
    return TimeEntry.objects.create(
        workspace=workspace,
        user=user,
        client=client,
        project=project,
        started_at=started,
        ended_at=started + timedelta(seconds=seconds),
        duration_seconds=seconds,
        hourly_rate=Decimal("100.00"),
        computed_amount=amount.quantize(Decimal("0.01")),
        billable=billable,
        billing_status=billing_status,
    )


class TestBusinessReport:
    def test_report_aggregates_revenue_hours_and_rates(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        today = timezone.localdate()
        Invoice.objects.create(
            workspace=workspace,
            client=client_record,
            status=InvoiceStatus.PAID,
            invoice_date=today - timedelta(days=10),
            paid_at=today - timedelta(days=3),
            net_amount=Decimal("1000.00"),
            gross_amount=Decimal("1190.00"),
        )
        make_entry(workspace, user, client_record, hours=10, days_ago=10)
        make_entry(
            workspace,
            user,
            client_record,
            hours=2,
            days_ago=5,
            billing_status=BillingStatus.OPEN,
        )
        make_entry(
            workspace,
            user,
            client_record,
            hours=3,
            days_ago=4,
            billing_status=BillingStatus.NOT_BILLABLE,
            billable=False,
        )

        report = business_report(workspace, today=today)

        assert report["kpis"]["revenue_ytd"] == "1000.00"
        # 1000 € über 10 abgerechnete Stunden.
        assert report["kpis"]["effective_hourly_rate"] == "100.00"
        # 12 von 15 Stunden abrechenbar.
        assert report["kpis"]["billable_share_90d"] == pytest.approx(0.8)
        assert report["kpis"]["avg_days_to_pay"] == 7
        assert report["kpis"]["unbilled_value"] == "200.00"

        assert len(report["months"]) == 12
        assert sum(Decimal(m["invoiced_net"]) for m in report["months"]) == Decimal("1000.00")
        assert sum(m["seconds"] for m in report["months"]) == 15 * 3600

        assert report["clients"][0]["name"] == "Acme GmbH"
        assert report["clients"][0]["share"] == pytest.approx(1.0)
        assert report["concentration"]["share"] == pytest.approx(1.0)

    def test_project_economics_and_budget_share(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        project = Project.objects.create(
            workspace=workspace,
            client=client_record,
            name="Website",
            budget_hours=Decimal("20.00"),
        )
        make_entry(
            workspace,
            user,
            client_record,
            hours=5,
            days_ago=3,
            billing_status=BillingStatus.OPEN,
            project=project,
        )

        report = business_report(workspace)

        row = next(p for p in report["projects"] if p["name"] == "Website")
        assert row["seconds"] == 5 * 3600
        assert row["budget_used_share"] == pytest.approx(0.25)
        assert row["unbilled_value"] == "500.00"

    def test_endpoint_requires_membership(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = auth_client.get("/api/v1/finance/report")
        assert response.status_code == 200
        assert "months" in response.data

    def test_empty_workspace_is_all_zero_but_valid(self, workspace: Workspace) -> None:
        report = business_report(workspace)
        assert report["kpis"]["revenue_ytd"] == "0.00"
        assert report["kpis"]["effective_hourly_rate"] is None
        assert report["kpis"]["billable_share_90d"] is None
        assert report["kpis"]["avg_days_to_pay"] is None
        assert report["clients"] == []
        assert report["concentration"] is None
        assert len(report["months"]) == 12
