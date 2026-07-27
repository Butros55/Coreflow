"""Service-type API: duplicate names must fail as a clear 400, not a DB 500."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User, Workspace
from apps.crm.models import Client
from apps.timetracking.models import BillingStatus, ServiceType, TimeEntry

pytestmark = pytest.mark.django_db

WORKSPACE_HEADER = "X-Workspace-ID"


class TestServiceTypeUniqueName:
    def test_duplicate_name_returns_german_validation_error(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        headers = {WORKSPACE_HEADER: str(workspace.pk)}
        first = auth_client.post(
            reverse("service-type-list"), {"name": "Entwicklung"}, format="json", headers=headers
        )
        assert first.status_code == 201

        # Case-insensitive: "entwicklung" would be indistinguishable in the UI.
        duplicate = auth_client.post(
            reverse("service-type-list"), {"name": "entwicklung"}, format="json", headers=headers
        )
        assert duplicate.status_code == 400
        error = duplicate.json()["error"]
        assert "existiert bereits" in error["message"]
        assert "name" in error["detail"]
        assert ServiceType.objects.filter(workspace=workspace).count() == 1

    def test_rename_to_own_name_still_allowed(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        headers = {WORKSPACE_HEADER: str(workspace.pk)}
        created = auth_client.post(
            reverse("service-type-list"), {"name": "Beratung"}, format="json", headers=headers
        )
        service_id = created.json()["id"]

        response = auth_client.patch(
            reverse("service-type-detail", args=[service_id]),
            {"name": "Beratung", "description": "Strategie"},
            format="json",
            headers=headers,
        )
        assert response.status_code == 200


class TestApplyRate:
    """The explicit re-pricing action after a rate change."""

    def _entry(
        self,
        workspace: Workspace,
        user: User,
        client: Client,
        service: ServiceType,
        *,
        billing_status: str = BillingStatus.OPEN,
        rate: str = "70.00",
    ) -> TimeEntry:
        started = timezone.now() - timedelta(days=1)
        return TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client,
            service_type=service,
            started_at=started,
            ended_at=started + timedelta(hours=2),
            duration_seconds=7200,
            hourly_rate=Decimal(rate),
            computed_amount=Decimal(rate) * 2,
            billable=True,
            billing_status=billing_status,
        )

    def test_open_entries_reprice_billed_stay_frozen(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        client = Client.objects.create(workspace=workspace, name="Acme", currency="EUR")
        service = ServiceType.objects.create(
            workspace=workspace, name="Entwicklung", default_hourly_rate=Decimal("90.00")
        )
        open_entry = self._entry(workspace, user, client, service)
        billed_entry = self._entry(
            workspace, user, client, service, billing_status=BillingStatus.BILLED
        )

        headers = {WORKSPACE_HEADER: str(workspace.pk)}
        response = auth_client.post(
            f"/api/v1/service-types/{service.pk}/apply-rate/", headers=headers
        )
        assert response.status_code == 200, response.content
        assert response.data["updated"] == 1

        open_entry.refresh_from_db()
        billed_entry.refresh_from_db()
        assert open_entry.hourly_rate == Decimal("90.00")
        assert open_entry.computed_amount == Decimal("180.00")
        assert billed_entry.hourly_rate == Decimal("70.00")

    def test_more_specific_rates_win_over_service_type(
        self, auth_client: APIClient, workspace: Workspace, user: User
    ) -> None:
        # Client has an own rate — the hierarchy keeps it above the service type.
        client = Client.objects.create(
            workspace=workspace,
            name="Premium AG",
            currency="EUR",
            default_hourly_rate=Decimal("120.00"),
        )
        service = ServiceType.objects.create(
            workspace=workspace, name="Beratung", default_hourly_rate=Decimal("90.00")
        )
        entry = self._entry(workspace, user, client, service, rate="120.00")

        headers = {WORKSPACE_HEADER: str(workspace.pk)}
        response = auth_client.post(
            f"/api/v1/service-types/{service.pk}/apply-rate/", headers=headers
        )
        assert response.status_code == 200
        assert response.data["updated"] == 0

        entry.refresh_from_db()
        assert entry.hourly_rate == Decimal("120.00")
