"""CRM API tests: numbering, primary contact, activity feed, isolation."""

from __future__ import annotations

from typing import Any

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import Workspace
from apps.crm.models import ActivityType, Client, ClientActivity, ClientContact

pytestmark = pytest.mark.django_db


class TestClientCrud:
    def test_create_assigns_workspace_and_number_server_side(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        response = auth_client.post(reverse("client-list"), {"name": "Neue Firma GmbH"})
        assert response.status_code == 201
        assert response.data["client_number"] == "K-1001"

        created = Client.objects.get(pk=response.data["id"])
        assert created.workspace_id == workspace.pk  # stamped, not client-chosen

    def test_numbers_increment(self, auth_client: APIClient) -> None:
        auth_client.post(reverse("client-list"), {"name": "Erste"})
        second = auth_client.post(reverse("client-list"), {"name": "Zweite"})
        assert second.data["client_number"] == "K-1002"

    def test_create_writes_an_activity(self, auth_client: APIClient) -> None:
        response = auth_client.post(reverse("client-list"), {"name": "Aktiv GmbH"})
        assert ClientActivity.objects.filter(
            client_id=response.data["id"], event_type=ActivityType.CLIENT_CREATED
        ).exists()

    def test_search_finds_by_name_and_number(self, auth_client: APIClient) -> None:
        auth_client.post(reverse("client-list"), {"name": "Bergblick Hotel"})
        auth_client.post(reverse("client-list"), {"name": "Talblick Pension"})

        by_name = auth_client.get(reverse("client-list"), {"search": "Bergblick"})
        assert by_name.data["count"] == 1

        by_number = auth_client.get(reverse("client-list"), {"search": "K-1002"})
        assert by_number.data["count"] == 1
        assert by_number.data["results"][0]["name"] == "Talblick Pension"

    def test_readonly_role_can_read_but_not_write(
        self, readonly_client: APIClient, auth_client: APIClient
    ) -> None:
        auth_client.post(reverse("client-list"), {"name": "Lesbar GmbH"})
        assert readonly_client.get(reverse("client-list")).status_code == 200
        assert readonly_client.post(reverse("client-list"), {"name": "Verboten"}).status_code == 403


class TestPrimaryContact:
    def test_making_a_contact_primary_demotes_the_previous_one(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        client = Client.objects.create(workspace=workspace, name="Firma")
        first = auth_client.post(
            reverse("client-contact-list"),
            {
                "client": str(client.pk),
                "first_name": "Anna",
                "last_name": "Alt",
                "is_primary": True,
            },
        )
        assert first.status_code == 201

        second = auth_client.post(
            reverse("client-contact-list"),
            {
                "client": str(client.pk),
                "first_name": "Bernd",
                "last_name": "Neu",
                "is_primary": True,
            },
        )
        assert second.status_code == 201

        primaries = ClientContact.objects.filter(client=client, is_primary=True)
        assert primaries.count() == 1
        primary = primaries.first()
        assert primary is not None and primary.first_name == "Bernd"


class TestClientStats:
    def test_list_contains_stats_from_real_data(
        self, auth_client: APIClient, workspace: Workspace, user: Any
    ) -> None:
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from apps.projects.models import Project
        from apps.timetracking.models import BillingStatus, TimeEntry

        client = Client.objects.create(workspace=workspace, name="Statistik GmbH")
        Project.objects.create(workspace=workspace, client=client, name="Aktiv", status="active")
        TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
            duration_seconds=3600,
            hourly_rate=Decimal("100.00"),
            computed_amount=Decimal("100.00"),
            billable=True,
            billing_status=BillingStatus.OPEN,
        )

        response = auth_client.get(reverse("client-list"), {"search": "Statistik"})
        stats = response.data["results"][0]["stats"]
        assert stats["active_projects"] == 1
        assert stats["open_seconds"] == 3600
        assert stats["open_amount"] == "100.00"

    def test_billed_time_does_not_count_as_open(
        self, auth_client: APIClient, workspace: Workspace, user: Any
    ) -> None:
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        from apps.timetracking.models import BillingStatus, TimeEntry

        client = Client.objects.create(workspace=workspace, name="Abgerechnet GmbH")
        TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
            duration_seconds=3600,
            hourly_rate=Decimal("100.00"),
            computed_amount=Decimal("100.00"),
            billable=True,
            billing_status=BillingStatus.BILLED,
        )
        response = auth_client.get(reverse("client-list"), {"search": "Abgerechnet"})
        assert response.data["results"][0]["stats"]["open_seconds"] == 0


class TestIsolation:
    def test_foreign_workspace_clients_are_invisible(
        self, auth_client: APIClient, other_workspace: Workspace
    ) -> None:
        foreign = Client.objects.create(workspace=other_workspace, name="Fremde AG")
        assert auth_client.get(reverse("client-list")).data["count"] == 0
        assert auth_client.get(reverse("client-detail", args=[foreign.pk])).status_code == 404

    def test_note_for_a_foreign_client_is_rejected(
        self, auth_client: APIClient, other_workspace: Workspace
    ) -> None:
        foreign = Client.objects.create(workspace=other_workspace, name="Fremde AG")
        response = auth_client.post(
            reverse("client-note-list"),
            {"client": str(foreign.pk), "content": "Einbruchsversuch"},
        )
        assert response.status_code == 400
