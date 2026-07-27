"""Timer lifecycle and the single-running-timer guarantee."""

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
from apps.timetracking.models import BillingStatus, EntrySource, TimeEntry
from apps.timetracking.services import apply_rounding

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_record(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace, name="Acme GmbH", default_hourly_rate=Decimal("100.00")
    )


class TestTimerEndpoints:
    def test_start_creates_a_running_entry_with_resolved_rate(
        self, auth_client: APIClient, client_record: Client
    ) -> None:
        response = auth_client.post(
            reverse("time-entry-start-timer"),
            {"client": str(client_record.pk), "description": "Arbeit"},
        )
        assert response.status_code == 201
        assert response.data["is_running"] is True
        assert response.data["ended_at"] is None
        # Client rate (100) beats workspace default (100.00 fixture default).
        assert response.data["hourly_rate"] == "100.00"
        assert response.data["source"] == EntrySource.TIMER

    def test_second_start_is_rejected_with_409(
        self, auth_client: APIClient, client_record: Client
    ) -> None:
        auth_client.post(reverse("time-entry-start-timer"), {"client": str(client_record.pk)})
        response = auth_client.post(
            reverse("time-entry-start-timer"), {"client": str(client_record.pk)}
        )
        assert response.status_code == 409
        assert response.data["error"]["code"] == "timer_already_running"

    def test_stop_computes_duration_and_amount(
        self, auth_client: APIClient, client_record: Client, workspace: Workspace, user: User
    ) -> None:
        # A timer that has been running for 30 minutes.
        TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client_record,
            started_at=timezone.now() - timedelta(minutes=30),
            ended_at=None,
            source=EntrySource.TIMER,
            hourly_rate=Decimal("100.00"),
        )
        response = auth_client.post(reverse("time-entry-stop-timer"))
        assert response.status_code == 200
        assert response.data["is_running"] is False
        seconds = response.data["duration_seconds"]
        assert 1795 <= seconds <= 1805  # ~30 min, allow test runtime jitter
        # ~0.5h × 100 €/h
        amount = Decimal(response.data["computed_amount"])
        assert Decimal("49.50") <= amount <= Decimal("50.50")
        assert response.data["billing_status"] == BillingStatus.OPEN

    def test_stop_without_running_timer_is_a_clean_404(self, auth_client: APIClient) -> None:
        response = auth_client.post(reverse("time-entry-stop-timer"))
        assert response.status_code == 404
        assert response.data["error"]["code"] == "no_running_timer"

    def test_timer_endpoint_reports_the_running_entry(
        self, auth_client: APIClient, client_record: Client
    ) -> None:
        assert auth_client.get(reverse("time-entry-timer")).data["running"] is None
        auth_client.post(reverse("time-entry-start-timer"), {"client": str(client_record.pk)})
        running = auth_client.get(reverse("time-entry-timer")).data["running"]
        assert running is not None
        # response.data is pre-rendered: PK fields are UUID objects, not strings
        assert running["client"] == client_record.pk

    def test_start_via_task_derives_project_and_client(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        from apps.projects.models import Board, Project, Task

        project = Project.objects.create(workspace=workspace, client=client_record, name="P1")
        board = Board.objects.create(workspace=workspace, project=project, name="B")
        task = Task.objects.create(
            workspace=workspace, project=project, board=board, title="T", created_by=user
        )
        response = auth_client.post(reverse("time-entry-start-timer"), {"task": str(task.pk)})
        assert response.status_code == 201
        assert response.data["project"] == project.pk
        assert response.data["client"] == client_record.pk


class TestSingleRunningTimerConstraint:
    def test_database_rejects_two_running_entries_for_one_user(
        self, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        """The guarantee must hold at the database, not just in the endpoint —
        an application-level check loses the race between two tabs."""
        TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client_record,
            started_at=timezone.now(),
            ended_at=None,
            hourly_rate=Decimal("95.00"),
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            TimeEntry.objects.create(
                workspace=workspace,
                user=user,
                client=client_record,
                started_at=timezone.now(),
                ended_at=None,
                hourly_rate=Decimal("95.00"),
            )

    def test_two_users_may_each_run_a_timer(
        self, workspace: Workspace, user: User, member_user: User, client_record: Client
    ) -> None:
        for u in (user, member_user):
            TimeEntry.objects.create(
                workspace=workspace,
                user=u,
                client=client_record,
                started_at=timezone.now(),
                ended_at=None,
                hourly_rate=Decimal("95.00"),
            )
        assert TimeEntry.objects.filter(ended_at__isnull=True).count() == 2


class TestRounding:
    @pytest.mark.parametrize(
        ("seconds", "increment", "strategy", "expected"),
        [
            (0, 15, "nearest", 0),
            (100, 0, "nearest", 100),  # rounding disabled
            (7 * 60, 15, "nearest", 15 * 60),  # 7 min → up to one increment
            (22 * 60, 15, "nearest", 15 * 60),  # 22 min → nearest is 15
            (23 * 60, 15, "nearest", 30 * 60),  # 23 min → nearest is 30
            (1 * 60, 15, "up", 15 * 60),
            (16 * 60, 15, "up", 30 * 60),
            (29 * 60, 15, "down", 15 * 60),
            (7 * 60, 15, "down", 15 * 60),  # never rounds worked time to zero
            (30 * 60, 15, "nearest", 30 * 60),  # exact multiple untouched
        ],
    )
    def test_apply_rounding(
        self, seconds: int, increment: int, strategy: str, expected: int
    ) -> None:
        assert apply_rounding(seconds, increment, strategy) == expected

    def test_stop_applies_workspace_rounding_and_keeps_the_original(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        workspace.time_rounding_increment_minutes = 15
        workspace.time_rounding_strategy = "up"
        workspace.save()
        TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client_record,
            started_at=timezone.now() - timedelta(minutes=17),
            ended_at=None,
            source=EntrySource.TIMER,
            hourly_rate=Decimal("100.00"),
        )
        response = auth_client.post(reverse("time-entry-stop-timer"))
        assert response.data["duration_seconds"] == 30 * 60
        original = response.data["rounded_from_seconds"]
        assert original is not None and 17 * 60 - 5 <= original <= 17 * 60 + 5


class TestManualEntries:
    def test_create_with_duration_computes_everything(
        self, auth_client: APIClient, client_record: Client
    ) -> None:
        started = timezone.now() - timedelta(hours=3)
        response = auth_client.post(
            reverse("time-entry-list"),
            {
                "client": str(client_record.pk),
                "started_at": started.isoformat(),
                "duration_input_seconds": 5400,  # 1.5 h
                "description": "Konzept",
            },
        )
        assert response.status_code == 201
        assert response.data["duration_seconds"] == 5400
        assert response.data["computed_amount"] == "150.00"  # 1.5 × 100
        assert response.data["billing_status"] == BillingStatus.OPEN

    def test_non_billable_entries_have_zero_amount_and_status(
        self, auth_client: APIClient, client_record: Client
    ) -> None:
        started = timezone.now() - timedelta(hours=1)
        response = auth_client.post(
            reverse("time-entry-list"),
            {
                "client": str(client_record.pk),
                "started_at": started.isoformat(),
                "duration_input_seconds": 3600,
                "billable": False,
            },
        )
        assert response.data["computed_amount"] == "0.00"
        assert response.data["billing_status"] == BillingStatus.NOT_BILLABLE

    def test_billed_entries_are_locked(
        self, auth_client: APIClient, workspace: Workspace, user: User, client_record: Client
    ) -> None:
        entry = TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=client_record,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
            duration_seconds=3600,
            hourly_rate=Decimal("100.00"),
            computed_amount=Decimal("100.00"),
            billing_status=BillingStatus.BILLED,
        )
        response = auth_client.patch(
            reverse("time-entry-detail", args=[entry.pk]), {"description": "Umschreiben"}
        )
        assert response.status_code == 400

    def test_readonly_member_cannot_track_time(
        self, readonly_client: APIClient, client_record: Client
    ) -> None:
        response = readonly_client.post(
            reverse("time-entry-start-timer"), {"client": str(client_record.pk)}
        )
        assert response.status_code == 403


class TestWorkspaceIsolation:
    def test_entries_from_another_workspace_are_invisible(
        self,
        auth_client: APIClient,
        other_workspace: Workspace,
        user: User,
        client_record: Client,
        workspace: Workspace,
    ) -> None:
        foreign_client = Client.objects.create(workspace=other_workspace, name="Fremd AG")
        foreign = TimeEntry.objects.create(
            workspace=other_workspace,
            user=user,
            client=foreign_client,
            started_at=timezone.now() - timedelta(hours=2),
            ended_at=timezone.now() - timedelta(hours=1),
            duration_seconds=3600,
            hourly_rate=Decimal("95.00"),
        )
        listing = auth_client.get(reverse("time-entry-list"))
        ids = {row["id"] for row in listing.data["results"]}
        assert str(foreign.pk) not in ids

        detail = auth_client.get(reverse("time-entry-detail", args=[foreign.pk]))
        assert detail.status_code == 404

    def test_manual_entry_cannot_reference_a_foreign_client(
        self, auth_client: APIClient, other_workspace: Workspace
    ) -> None:
        foreign_client = Client.objects.create(workspace=other_workspace, name="Fremd AG")
        response = auth_client.post(
            reverse("time-entry-list"),
            {
                "client": str(foreign_client.pk),
                "started_at": timezone.now().isoformat(),
                "duration_input_seconds": 3600,
            },
        )
        assert response.status_code == 400  # related queryset is workspace-filtered
