"""Clockify sync: mirroring, idempotency, dedup, conflicts, webhooks, pushes.

Everything runs against respx mocks — the suite's autouse ``_no_network`` guard
makes a missed mock a loud failure instead of a live API call. The test
settings pin ``CLOCKIFY_WORKSPACE_ID=ws-1`` so no test needs to mock the
``/user`` workspace discovery.
"""

from __future__ import annotations

import datetime as dt
import json
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
from apps.crm.models import Client
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.clockify.client import ClockifyClient
from apps.integrations.clockify.sync import (
    NO_CLIENT_PLACEHOLDER,
    ClockifySync,
    push_entries_billed,
)
from apps.integrations.models import (
    ExternalObjectLink,
    Provider,
    ProviderProfile,
    SyncConflict,
    WebhookEvent,
)
from apps.invoicing.models import (
    Invoice,
    InvoiceLine,
    InvoiceLinkSource,
    InvoiceStatus,
    InvoiceTimeEntry,
)
from apps.projects.models import Project
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry

pytestmark = pytest.mark.django_db

BASE = "https://api.clockify.me/api/v1"
WS = f"{BASE}/workspaces/ws-1"

CLOCKIFY_ON = {
    "CLOCKIFY_ENABLED": True,
    "CLOCKIFY_API_KEY": "secret-key",
}


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


def remote_entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "e-9001",
        "description": "API-Anbindung",
        "userId": "u-5",
        "projectId": "p-21",
        "taskId": None,
        "billable": True,
        "tagIds": [],
        "workspaceId": "ws-1",
        "timeInterval": {
            "start": "2026-07-10T09:00:00Z",
            "end": "2026-07-10T11:30:00Z",
            "duration": "PT2H30M",
        },
    }
    entry.update(overrides)
    return entry


def link_user(workspace: Workspace, local: User, external_id: str = "u-5") -> ExternalObjectLink:
    return ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.CLOCKIFY,
        resource_type="user",
        external_id=external_id,
        local_object_type="accounts.User",
        local_object_id=local.pk,
    )


def link_project(
    workspace: Workspace, project: Project, external_id: str = "p-21"
) -> ExternalObjectLink:
    return ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.CLOCKIFY,
        resource_type="project",
        external_id=external_id,
        local_object_type="projects.Project",
        local_object_id=project.pk,
    )


def link_entry(workspace: Workspace, entry: TimeEntry, external_id: str) -> ExternalObjectLink:
    return ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.CLOCKIFY,
        resource_type="entry",
        external_id=external_id,
        local_object_type="timetracking.TimeEntry",
        local_object_id=entry.pk,
    )


@pytest.fixture
def local_client(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace, name="Acme GmbH", default_hourly_rate=Decimal("80.00")
    )


@pytest.fixture
def local_project(workspace: Workspace, local_client: Client) -> Project:
    return Project.objects.create(workspace=workspace, client=local_client, name="Relaunch")


def mock_entry_listing(entries: list[dict[str, Any]], user_id: str = "u-5") -> Any:
    return respx.get(f"{WS}/user/{user_id}/time-entries").mock(
        return_value=httpx.Response(200, json=entries)
    )


def sync_entries_window(workspace: Workspace, conn: ClockifyClient) -> Any:
    now = timezone.now()
    return ClockifySync(workspace, trigger="manual").sync_entries(
        conn, since=now - dt.timedelta(days=30), until=now
    )


class TestClientSync:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @respx.mock
    def test_remote_client_becomes_local_mirror(self, workspace: Workspace) -> None:
        respx.get(f"{WS}/clients").mock(
            return_value=httpx.Response(
                200, json=[{"id": "c-11", "name": "Neukunde AG", "archived": False}]
            )
        )
        with ClockifyClient() as conn:
            job = ClockifySync(workspace).sync_clients(conn)

        created = Client.objects.get(workspace=workspace, name="Neukunde AG")
        link = ExternalObjectLink.objects.get(
            workspace=workspace, provider=Provider.CLOCKIFY, resource_type="client"
        )
        assert link.local_object_id == created.pk
        assert link.external_id == "c-11"
        assert job.records_created == 1

    @respx.mock
    def test_name_match_links_instead_of_duplicating(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        respx.get(f"{WS}/clients").mock(
            return_value=httpx.Response(
                200, json=[{"id": "c-11", "name": "acme gmbh", "archived": False}]
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_clients(conn)

        assert Client.objects.filter(workspace=workspace).count() == 1
        link = ExternalObjectLink.objects.get(
            workspace=workspace, provider=Provider.CLOCKIFY, resource_type="client"
        )
        assert link.local_object_id == local_client.pk

    @respx.mock
    def test_unlinked_local_client_is_pushed(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        respx.get(f"{WS}/clients").mock(return_value=httpx.Response(200, json=[]))
        create_route = respx.post(f"{WS}/clients").mock(
            return_value=httpx.Response(
                201, json={"id": "c-77", "name": "Acme GmbH", "archived": False}
            )
        )
        with ClockifyClient() as conn:
            job = ClockifySync(workspace).sync_clients(conn)

        assert create_route.called
        payload = json.loads(create_route.calls.last.request.content)
        assert payload == {"name": "Acme GmbH"}
        assert ExternalObjectLink.objects.filter(
            workspace=workspace, resource_type="client", external_id="c-77"
        ).exists()
        assert job.records_created == 1

    @respx.mock
    def test_second_run_is_a_no_op(self, workspace: Workspace) -> None:
        respx.get(f"{WS}/clients").mock(
            return_value=httpx.Response(
                200, json=[{"id": "c-11", "name": "Neukunde AG", "archived": False}]
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_clients(conn)
            job2 = ClockifySync(workspace).sync_clients(conn)

        assert Client.objects.filter(workspace=workspace).count() == 1
        assert job2.records_created == 0
        assert job2.records_skipped == 1


class TestTagAndUserSync:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @respx.mock
    def test_tag_matches_local_service_type_by_name(self, workspace: Workspace) -> None:
        existing = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        respx.get(f"{WS}/tags").mock(
            return_value=httpx.Response(
                200, json=[{"id": "t-3", "name": "entwicklung", "archived": False}]
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_tags(conn)

        link = ExternalObjectLink.objects.get(
            workspace=workspace, provider=Provider.CLOCKIFY, resource_type="tag"
        )
        assert link.local_object_id == existing.pk
        assert ServiceType.objects.filter(workspace=workspace).count() == 1

    @respx.mock
    def test_billed_marker_tag_never_becomes_a_service_type(self, workspace: Workspace) -> None:
        respx.get(f"{WS}/tags").mock(
            return_value=httpx.Response(
                200, json=[{"id": "t-b", "name": "Abgerechnet", "archived": False}]
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_tags(conn)

        assert ServiceType.objects.filter(workspace=workspace).count() == 0
        assert not ExternalObjectLink.objects.filter(resource_type="tag").exists()

    @respx.mock
    def test_unlinked_service_type_is_pushed(self, workspace: Workspace) -> None:
        ServiceType.objects.create(workspace=workspace, name="Beratung")
        respx.get(f"{WS}/tags").mock(return_value=httpx.Response(200, json=[]))
        create_route = respx.post(f"{WS}/tags").mock(
            return_value=httpx.Response(201, json={"id": "t-8", "name": "Beratung"})
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_tags(conn)
        assert create_route.called

    @respx.mock
    def test_users_matched_by_email_only(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        respx.get(f"{WS}/users").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": "u-5", "name": "Olive", "email": "OWNER@example.com"},
                    {"id": "u-6", "name": "Fremd", "email": "stranger@example.com"},
                ],
            )
        )
        with ClockifyClient() as conn:
            job = ClockifySync(workspace).sync_users(conn)

        links = ExternalObjectLink.objects.filter(
            workspace=workspace, provider=Provider.CLOCKIFY, resource_type="user"
        )
        assert links.count() == 1
        assert links.get().local_object_id == user.pk
        assert job.records_created == 1
        assert job.records_skipped == 1  # No local account for the stranger.


class TestProjectSync:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @respx.mock
    def test_remote_project_mirrors_under_linked_client(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKIFY,
            resource_type="client",
            external_id="c-11",
            local_object_type="crm.Client",
            local_object_id=local_client.pk,
        )
        respx.get(f"{WS}/projects").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "p-21", "clientId": "c-11", "name": "Relaunch", "archived": False}],
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_projects(conn)

        project = Project.objects.get(workspace=workspace, name="Relaunch")
        assert project.client == local_client
        assert ExternalObjectLink.objects.filter(
            resource_type="project", external_id="p-21"
        ).exists()

    @respx.mock
    def test_project_without_client_lands_on_placeholder(self, workspace: Workspace) -> None:
        """Clockify projects may have no client; local ones cannot."""
        respx.get(f"{WS}/projects").mock(
            return_value=httpx.Response(
                200, json=[{"id": "p-9", "clientId": "", "name": "Intern", "archived": False}]
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_projects(conn)

        project = Project.objects.get(workspace=workspace, name="Intern")
        assert project.client.name == NO_CLIENT_PLACEHOLDER

    @respx.mock
    def test_unlinked_local_project_is_pushed_with_client_id(
        self, workspace: Workspace, local_client: Client, local_project: Project
    ) -> None:
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKIFY,
            resource_type="client",
            external_id="c-11",
            local_object_type="crm.Client",
            local_object_id=local_client.pk,
        )
        respx.get(f"{WS}/projects").mock(return_value=httpx.Response(200, json=[]))
        create_route = respx.post(f"{WS}/projects").mock(
            return_value=httpx.Response(
                201,
                json={"id": "p-70", "clientId": "c-11", "name": "Relaunch", "archived": False},
            )
        )
        with ClockifyClient() as conn:
            ClockifySync(workspace).sync_projects(conn)

        assert create_route.called
        payload = json.loads(create_route.calls.last.request.content)
        assert payload["name"] == "Relaunch"
        assert payload["clientId"] == "c-11"
        assert ExternalObjectLink.objects.filter(
            resource_type="project", external_id="p-70"
        ).exists()


class TestEntrySync:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @pytest.fixture
    def linked_refs(
        self, workspace: Workspace, user: User, local_client: Client, local_project: Project
    ) -> None:
        link_user(workspace, user)
        link_project(workspace, local_project)

    @respx.mock
    def test_remote_entry_becomes_time_entry(
        self, workspace: Workspace, user: User, local_client: Client, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            job = sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.source == EntrySource.CLOCKIFY
        assert entry.user == user
        assert entry.client == local_client
        assert entry.duration_seconds == 9000
        assert entry.description == "API-Anbindung"
        # No remote rate is mirrored — the local chain prices it (client 80.00).
        assert entry.hourly_rate == Decimal("80.00")
        assert entry.computed_amount == Decimal("200.00")  # 2.5h × 80
        assert entry.billing_status == BillingStatus.OPEN
        assert entry.started_at == dt.datetime(2026, 7, 10, 9, 0, tzinfo=dt.UTC)
        assert job.records_created == 1

    @respx.mock
    def test_non_billable_maps_to_local_status(
        self, workspace: Workspace, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry(id="e-1", billable=False)])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        assert entry.billable is False
        assert entry.billing_status == BillingStatus.NOT_BILLABLE
        assert entry.computed_amount == Decimal("0.00")

    @respx.mock
    def test_running_entry_is_skipped(self, workspace: Workspace, linked_refs: None) -> None:
        running = remote_entry()
        running["timeInterval"] = {"start": "2026-07-10T09:00:00Z", "end": None, "duration": None}
        mock_entry_listing([running])
        with ClockifyClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 0
        assert job.records_skipped == 1

    @respx.mock
    def test_unknown_clockify_user_is_skipped(
        self, workspace: Workspace, user: User, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry(userId="u-999")])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)
        assert TimeEntry.objects.count() == 0

    @respx.mock
    def test_entry_without_project_lands_on_placeholder_client(
        self, workspace: Workspace, user: User
    ) -> None:
        link_user(workspace, user)
        mock_entry_listing([remote_entry(projectId=None)])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        assert entry.client.name == NO_CLIENT_PLACEHOLDER
        assert entry.project is None

    @respx.mock
    def test_second_sync_is_idempotent(self, workspace: Workspace, linked_refs: None) -> None:
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)
            job2 = sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 1
        assert job2.records_created == 0
        assert job2.records_skipped == 1

    @respx.mock
    def test_remote_edit_updates_untouched_local(
        self, workspace: Workspace, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        edited = remote_entry(description="Korrigierter Text")
        edited["timeInterval"] = {
            "start": "2026-07-10T09:00:00Z",
            "end": "2026-07-10T12:00:00Z",
            "duration": "PT3H",
        }
        mock_entry_listing([edited])
        with ClockifyClient() as conn:
            job = sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        assert entry.description == "Korrigierter Text"
        assert entry.duration_seconds == 10800
        assert entry.computed_amount == Decimal("240.00")  # 3h × 80
        assert job.records_updated == 1

    @respx.mock
    def test_local_edit_is_pushed_back_when_remote_unchanged(
        self, workspace: Workspace, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        entry.description = "Lokal präzisiert"
        entry.save()

        push_route = respx.put(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry(description="Lokal präzisiert"))
        )
        with ClockifyClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert push_route.called
        payload = json.loads(push_route.calls.last.request.content)
        assert payload["description"] == "Lokal präzisiert"
        # PUT replaces remotely — the project mapping must survive the push.
        assert payload["projectId"] == "p-21"
        assert payload["start"] == "2026-07-10T09:00:00Z"
        assert job.records_updated == 1  # counted as pushed
        assert SyncConflict.objects.count() == 0

    @respx.mock
    def test_concurrent_divergence_becomes_conflict(
        self, workspace: Workspace, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        entry.description = "Lokal geändert"
        entry.save()

        mock_entry_listing([remote_entry(description="Remote geändert")])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        conflict = SyncConflict.objects.get()
        assert conflict.reason == "concurrent_modification"
        entry.refresh_from_db()
        # Local version untouched — a human decides.
        assert entry.description == "Lokal geändert"

    @respx.mock
    def test_remote_edit_of_billed_entry_is_a_conflict(
        self, workspace: Workspace, linked_refs: None
    ) -> None:
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        TimeEntry.objects.update(billing_status=BillingStatus.BILLED)
        shortened = remote_entry()
        shortened["timeInterval"] = {
            "start": "2026-07-10T09:00:00Z",
            "end": "2026-07-10T09:01:00Z",
            "duration": "PT1M",
        }
        mock_entry_listing([shortened])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        assert SyncConflict.objects.filter(resource_type="entry").count() == 1
        entry = TimeEntry.objects.get()
        assert entry.duration_seconds == 9000  # untouched

    @respx.mock
    def test_own_billed_tag_echo_is_not_a_conflict(
        self, workspace: Workspace, linked_refs: None
    ) -> None:
        """After we push the billed tag, the next sync sees changed tagIds —
        which must read as convergence, not divergence."""
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        TimeEntry.objects.update(billing_status=BillingStatus.BILLED)
        mock_entry_listing([remote_entry(tagIds=["t-billed"])])
        with ClockifyClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert SyncConflict.objects.count() == 0
        assert job.records_skipped == 1  # convergent → unchanged

    @respx.mock
    def test_unlinked_project_is_fetched_on_demand(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        """An entry for a never-synced project pulls project + client mid-flight."""
        link_user(workspace, user)
        mock_entry_listing([remote_entry(projectId="p-44")])
        respx.get(f"{WS}/projects/p-44").mock(
            return_value=httpx.Response(
                200,
                json={"id": "p-44", "clientId": "c-44", "name": "Spontan", "archived": False},
            )
        )
        respx.get(f"{WS}/clients/c-44").mock(
            return_value=httpx.Response(
                200, json={"id": "c-44", "name": "Spontan GmbH", "archived": False}
            )
        )
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        assert Client.objects.filter(workspace=workspace, name="Spontan GmbH").exists()
        assert Project.objects.filter(workspace=workspace, name="Spontan").exists()
        assert TimeEntry.objects.count() == 1


class TestLexwareDedup:
    """The 'one entry, two tags' rule: a Clockify entry that already exists
    locally (tracked twin or Lexware reconstruction) is linked, not duplicated."""

    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @pytest.fixture
    def linked_refs(
        self, workspace: Workspace, user: User, local_client: Client, local_project: Project
    ) -> None:
        link_user(workspace, user)
        link_project(workspace, local_project)

    @respx.mock
    def test_exact_local_twin_is_linked_not_duplicated(
        self, workspace: Workspace, user: User, local_client: Client, linked_refs: None
    ) -> None:
        twin = TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=local_client,
            description="API-Anbindung",
            started_at=dt.datetime(2026, 7, 10, 9, 0, tzinfo=dt.UTC),
            ended_at=dt.datetime(2026, 7, 10, 11, 30, tzinfo=dt.UTC),
            duration_seconds=9000,
            source=EntrySource.MANUAL,
            billable=True,
            hourly_rate=Decimal("80.00"),
            computed_amount=Decimal("200.00"),
        )
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 1  # linked, NOT duplicated
        link = ExternalObjectLink.objects.get(resource_type="entry", external_id="e-9001")
        assert link.local_object_id == twin.pk
        twin.refresh_from_db()
        assert twin.source == EntrySource.MANUAL  # provenance untouched
        assert job.records_updated == 1  # counted as merged

    @respx.mock
    def test_lexware_reconstruction_gains_clockify_link(
        self, workspace: Workspace, user: User, local_client: Client, linked_refs: None
    ) -> None:
        """A reconstruction has synthetic times (stacked from 09:00 of the
        period start) — the match runs on client + hours + invoice period."""
        invoice = Invoice.objects.create(
            workspace=workspace,
            client=local_client,
            status=InvoiceStatus.PAID,
            period_start=dt.date(2026, 7, 1),
            period_end=dt.date(2026, 7, 31),
        )
        line = InvoiceLine.objects.create(
            workspace=workspace,
            invoice=invoice,
            title="Entwicklung",
            quantity=Decimal("2.50"),
            unit="Std.",
            unit_price=Decimal("95.00"),
            total_price=Decimal("237.50"),
        )
        # Reconstructed at 09:00 of July 1st — NOT when the work happened.
        reconstructed = TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=local_client,
            description="Entwicklung",
            started_at=dt.datetime(2026, 7, 1, 7, 0, tzinfo=dt.UTC),
            ended_at=dt.datetime(2026, 7, 1, 9, 30, tzinfo=dt.UTC),
            duration_seconds=9000,
            source=EntrySource.LEXWARE,
            billable=True,
            hourly_rate=Decimal("95.00"),
            computed_amount=Decimal("237.50"),
            billing_status=BillingStatus.BILLED,
        )
        InvoiceTimeEntry.objects.create(
            workspace=workspace,
            invoice=invoice,
            invoice_line=line,
            time_entry=reconstructed,
            duration_seconds_taken=9000,
            amount_taken=Decimal("237.50"),
            source=InvoiceLinkSource.LEXWARE_IMPORT,
        )

        # The real work happened on July 10th, tracked in Clockify: same
        # client, same 2.5 h, inside the invoice's service period.
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 1  # ONE entry, not two
        link = ExternalObjectLink.objects.get(resource_type="entry", external_id="e-9001")
        assert link.local_object_id == reconstructed.pk

        reconstructed.refresh_from_db()
        # Billed facts stay exactly as billed; only the Clockify identity is added.
        assert reconstructed.source == EntrySource.LEXWARE
        assert reconstructed.billing_status == BillingStatus.BILLED
        assert reconstructed.duration_seconds == 9000
        assert reconstructed.started_at == dt.datetime(2026, 7, 1, 7, 0, tzinfo=dt.UTC)

    @respx.mock
    def test_entry_outside_invoice_period_is_not_merged(
        self, workspace: Workspace, user: User, local_client: Client, linked_refs: None
    ) -> None:
        invoice = Invoice.objects.create(
            workspace=workspace,
            client=local_client,
            status=InvoiceStatus.PAID,
            period_start=dt.date(2026, 5, 1),
            period_end=dt.date(2026, 5, 31),
        )
        line = InvoiceLine.objects.create(
            workspace=workspace, invoice=invoice, title="Entwicklung", quantity=Decimal("2.50")
        )
        reconstructed = TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=local_client,
            started_at=dt.datetime(2026, 5, 1, 7, 0, tzinfo=dt.UTC),
            ended_at=dt.datetime(2026, 5, 1, 9, 30, tzinfo=dt.UTC),
            duration_seconds=9000,
            source=EntrySource.LEXWARE,
            billable=True,
            hourly_rate=Decimal("95.00"),
            computed_amount=Decimal("237.50"),
            billing_status=BillingStatus.BILLED,
        )
        InvoiceTimeEntry.objects.create(
            workspace=workspace,
            invoice=invoice,
            invoice_line=line,
            time_entry=reconstructed,
            duration_seconds_taken=9000,
            amount_taken=Decimal("237.50"),
            source=InvoiceLinkSource.LEXWARE_IMPORT,
        )

        # July entry vs. a May invoice: same hours, but NOT the same work.
        mock_entry_listing([remote_entry()])
        with ClockifyClient() as conn:
            sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 2
        link = ExternalObjectLink.objects.get(resource_type="entry", external_id="e-9001")
        assert link.local_object_id != reconstructed.pk

    @respx.mock
    def test_integration_tags_show_both_systems(
        self,
        workspace: Workspace,
        user: User,
        local_client: Client,
        linked_refs: None,
        auth_client: APIClient,
    ) -> None:
        """The API exposes the dedup result: one row, both tags."""
        invoice = Invoice.objects.create(
            workspace=workspace,
            client=local_client,
            status=InvoiceStatus.PAID,
            period_start=dt.date(2026, 7, 1),
            period_end=dt.date(2026, 7, 31),
        )
        line = InvoiceLine.objects.create(
            workspace=workspace, invoice=invoice, title="Entwicklung", quantity=Decimal("2.50")
        )
        entry = TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=local_client,
            started_at=dt.datetime(2026, 7, 1, 7, 0, tzinfo=dt.UTC),
            ended_at=dt.datetime(2026, 7, 1, 9, 30, tzinfo=dt.UTC),
            duration_seconds=9000,
            source=EntrySource.LEXWARE,
            billable=True,
            hourly_rate=Decimal("95.00"),
            computed_amount=Decimal("237.50"),
            billing_status=BillingStatus.BILLED,
        )
        InvoiceTimeEntry.objects.create(
            workspace=workspace,
            invoice=invoice,
            invoice_line=line,
            time_entry=entry,
            duration_seconds_taken=9000,
            amount_taken=Decimal("237.50"),
            source=InvoiceLinkSource.LEXWARE_IMPORT,
        )
        link_entry(workspace, entry, "e-9001")

        response = auth_client.get(reverse("time-entry-detail", args=[entry.pk]))
        assert response.status_code == 200
        assert sorted(response.data["integration_tags"]) == ["clockify", "lexware"]


class TestOutboundPush:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    def _profile(self, workspace: Workspace) -> ProviderProfile:
        return ProviderProfile.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKIFY,
            external_organization_id="ws-1",
            raw_profile={"user": {"id": "u-5"}},
        )

    def _local_entry(
        self, workspace: Workspace, user: User, local_client: Client, **overrides: Any
    ) -> TimeEntry:
        defaults: dict[str, Any] = {
            "workspace": workspace,
            "user": user,
            "client": local_client,
            "description": "Lokal getrackt",
            "started_at": timezone.now() - dt.timedelta(hours=3),
            "ended_at": timezone.now() - dt.timedelta(hours=1),
            "duration_seconds": 7200,
            "source": EntrySource.MANUAL,
            "billable": True,
            "hourly_rate": Decimal("80.00"),
            "computed_amount": Decimal("160.00"),
        }
        defaults.update(overrides)
        return TimeEntry.objects.create(**defaults)

    @respx.mock
    def test_unlinked_local_entry_is_created_in_clockify(
        self,
        workspace: Workspace,
        user: User,
        local_client: Client,
        local_project: Project,
    ) -> None:
        self._profile(workspace)
        link_user(workspace, user)
        link_project(workspace, local_project)
        entry = self._local_entry(workspace, user, local_client, project=local_project)

        create_route = respx.post(f"{WS}/time-entries").mock(
            return_value=httpx.Response(201, json=remote_entry(id="e-77"))
        )
        with ClockifyClient() as conn:
            job = ClockifySync(workspace).push_local_entries(conn)

        assert create_route.called
        payload = json.loads(create_route.calls.last.request.content)
        assert payload["projectId"] == "p-21"
        assert payload["description"] == "Lokal getrackt"
        link = ExternalObjectLink.objects.get(resource_type="entry", external_id="e-77")
        assert link.local_object_id == entry.pk
        assert job.records_created == 1

    @respx.mock
    def test_lexware_reconstructions_are_never_pushed(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        self._profile(workspace)
        link_user(workspace, user)
        self._local_entry(workspace, user, local_client, source=EntrySource.LEXWARE)

        with ClockifyClient() as conn:
            job = ClockifySync(workspace).push_local_entries(conn)
        # No POST route mocked: a push attempt would crash the test.
        assert job.records_processed == 0

    @respx.mock
    def test_member_without_clockify_identity_is_skipped(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        self._profile(workspace)
        self._local_entry(workspace, user, local_client)

        with ClockifyClient() as conn:
            job = ClockifySync(workspace).push_local_entries(conn)
        assert job.records_skipped == 1

    @respx.mock
    def test_push_time_entry_task_mirrors_a_local_change(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.integrations.clockify.tasks import push_time_entry

        self._profile(workspace)
        link_user(workspace, user)
        entry = self._local_entry(workspace, user, local_client)
        respx.post(f"{WS}/time-entries").mock(
            return_value=httpx.Response(201, json=remote_entry(id="e-88", projectId=None))
        )

        assert push_time_entry(str(workspace.pk), str(entry.pk)) == "created"
        assert ExternalObjectLink.objects.filter(resource_type="entry", external_id="e-88").exists()

    @respx.mock
    def test_local_deletion_is_mirrored(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.integrations.clockify.tasks import delete_time_entry_remote

        entry = self._local_entry(workspace, user, local_client)
        link_entry(workspace, entry, "e-9001")
        delete_route = respx.delete(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(204)
        )

        result = delete_time_entry_remote(str(workspace.pk), "e-9001")
        assert result == "deleted"
        assert delete_route.called
        assert not ExternalObjectLink.objects.filter(resource_type="entry").exists()

    @respx.mock
    def test_api_delete_enqueues_the_remote_deletion(
        self,
        workspace: Workspace,
        user: User,
        local_client: Client,
        auth_client: APIClient,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        entry = self._local_entry(workspace, user, local_client)
        link_entry(workspace, entry, "e-9001")
        delete_route = respx.delete(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(204)
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = auth_client.delete(reverse("time-entry-detail", args=[entry.pk]))
        assert response.status_code == 204
        assert delete_route.called


class TestBilledPush:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @respx.mock
    def test_billed_entries_get_the_billed_tag(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.invoicing.tests.test_invoicing import make_entry

        linked = make_entry(workspace, user, local_client, billing_status=BillingStatus.BILLED)
        make_entry(workspace, user, local_client, billing_status=BillingStatus.BILLED)
        link_entry(workspace, linked, "e-9001")

        respx.get(f"{WS}/tags").mock(
            return_value=httpx.Response(200, json=[{"id": "t-billed", "name": "Abgerechnet"}])
        )
        respx.get(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry())
        )
        put_route = respx.put(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry(tagIds=["t-billed"]))
        )

        pushed = push_entries_billed(workspace, [linked.pk])
        assert pushed == 1
        payload = json.loads(put_route.calls.last.request.content)
        assert payload["tagIds"] == ["t-billed"]
        # Every other remote field survives the tag write untouched.
        assert payload["start"] == "2026-07-10T09:00:00Z"
        assert payload["projectId"] == "p-21"

    @respx.mock
    def test_missing_billed_tag_is_created_once(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.invoicing.tests.test_invoicing import make_entry

        entry = make_entry(workspace, user, local_client, billing_status=BillingStatus.BILLED)
        link_entry(workspace, entry, "e-9001")

        respx.get(f"{WS}/tags").mock(return_value=httpx.Response(200, json=[]))
        tag_route = respx.post(f"{WS}/tags").mock(
            return_value=httpx.Response(201, json={"id": "t-new", "name": "Abgerechnet"})
        )
        respx.get(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry())
        )
        respx.put(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry(tagIds=["t-new"]))
        )

        assert push_entries_billed(workspace, [entry.pk]) == 1
        assert tag_route.called

    @respx.mock
    def test_mark_entries_billed_enqueues_the_push(
        self,
        workspace: Workspace,
        user: User,
        local_client: Client,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        """The invoicing hook fires the Clockify mirror task after commit."""
        from apps.invoicing.services import compose_invoice, mark_entries_billed
        from apps.invoicing.tests.test_invoicing import make_entry

        entry = make_entry(workspace, user, local_client, hours=1)
        link_entry(workspace, entry, "e-9001")
        invoice = compose_invoice(
            workspace=workspace,
            client=local_client,
            entry_ids=[str(entry.pk)],
            grouping="lump_sum",
        )
        respx.get(f"{WS}/tags").mock(
            return_value=httpx.Response(200, json=[{"id": "t-billed", "name": "Abgerechnet"}])
        )
        respx.get(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry())
        )
        put_route = respx.put(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry(tagIds=["t-billed"]))
        )
        with django_capture_on_commit_callbacks(execute=True):
            mark_entries_billed(invoice)

        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.BILLED
        assert put_route.called


class TestWebhookReceiver:
    URL = "/webhooks/clockify/"

    def _profile(self, workspace: Workspace) -> ProviderProfile:
        return ProviderProfile.objects.create(
            workspace=workspace, provider=Provider.CLOCKIFY, company_name="Testfirma"
        )

    def _post(self, api_client: APIClient, event: str, body: dict[str, Any], token: str) -> Any:
        return api_client.post(
            self.URL,
            body,
            format="json",
            HTTP_CLOCKIFY_SIGNATURE=token,
            HTTP_CLOCKIFY_WEBHOOK_EVENT_TYPE=event,
        )

    def test_disabled_integration_is_dark(self, api_client: APIClient) -> None:
        response = api_client.post(self.URL, {}, format="json")
        assert response.status_code == 404

    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="tok-a,tok-b")
    def test_bad_signature_is_rejected_without_persisting(
        self, api_client: APIClient, workspace: Workspace
    ) -> None:
        self._profile(workspace)
        response = self._post(api_client, "NEW_TIME_ENTRY", remote_entry(), "WRONG")
        assert response.status_code == 403
        assert WebhookEvent.objects.count() == 0

    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="tok-a,tok-b")
    def test_any_configured_token_is_accepted(
        self, api_client: APIClient, workspace: Workspace
    ) -> None:
        """Each Clockify webhook has its own token — all of them must verify."""
        self._profile(workspace)
        response = self._post(api_client, "UNSUBSCRIBED_EVENT", {"id": "x"}, "tok-b")
        assert response.status_code == 200
        event = WebhookEvent.objects.get()
        assert event.processing_status == "ignored"
        assert event.signature_verified is True

    @respx.mock
    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="hook-token")
    def test_new_time_entry_event_is_fetched_and_mirrored(
        self,
        api_client: APIClient,
        workspace: Workspace,
        user: User,
        local_client: Client,
        local_project: Project,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        self._profile(workspace)
        link_user(workspace, user)
        link_project(workspace, local_project)
        respx.get(f"{WS}/time-entries/e-9001").mock(
            return_value=httpx.Response(200, json=remote_entry())
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = self._post(api_client, "NEW_TIME_ENTRY", remote_entry(), "hook-token")
        assert response.status_code == 200

        event = WebhookEvent.objects.get(event_type="NEW_TIME_ENTRY")
        assert event.processing_status == "processed"
        assert event.external_resource_id == "e-9001"
        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.source == EntrySource.CLOCKIFY

    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="hook-token")
    def test_identical_delivery_is_deduplicated_but_changes_are_not(
        self, api_client: APIClient, workspace: Workspace
    ) -> None:
        self._profile(workspace)
        body = remote_entry()
        first = self._post(api_client, "TIME_ENTRY_UPDATED", body, "hook-token")
        second = self._post(api_client, "TIME_ENTRY_UPDATED", body, "hook-token")
        changed = self._post(
            api_client, "TIME_ENTRY_UPDATED", remote_entry(description="Neu"), "hook-token"
        )
        assert first.status_code == 200
        assert second.data.get("duplicate") is True
        assert changed.data.get("duplicate") is None
        assert WebhookEvent.objects.filter(event_type="TIME_ENTRY_UPDATED").count() == 2

    @respx.mock
    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="hook-token")
    def test_entry_deleted_removes_unbilled_mirror(
        self,
        api_client: APIClient,
        workspace: Workspace,
        user: User,
        local_client: Client,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        from apps.invoicing.tests.test_invoicing import make_entry

        self._profile(workspace)
        entry = make_entry(workspace, user, local_client)
        link = link_entry(workspace, entry, "e-9001")

        with django_capture_on_commit_callbacks(execute=True):
            self._post(api_client, "TIME_ENTRY_DELETED", remote_entry(), "hook-token")

        assert not TimeEntry.objects.filter(pk=entry.pk).exists()
        link.refresh_from_db()
        assert link.deleted_remotely is True

    @respx.mock
    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="hook-token")
    def test_entry_deleted_with_billed_local_becomes_conflict(
        self,
        api_client: APIClient,
        workspace: Workspace,
        user: User,
        local_client: Client,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        from apps.invoicing.tests.test_invoicing import make_entry

        self._profile(workspace)
        entry = make_entry(workspace, user, local_client, billing_status=BillingStatus.BILLED)
        link_entry(workspace, entry, "e-9001")

        with django_capture_on_commit_callbacks(execute=True):
            self._post(api_client, "TIME_ENTRY_DELETED", remote_entry(), "hook-token")

        assert TimeEntry.objects.filter(pk=entry.pk).exists()  # never deleted
        conflict = SyncConflict.objects.get()
        assert conflict.reason == "remote_deleted"

    @respx.mock
    @override_settings(**CLOCKIFY_ON, CLOCKIFY_WEBHOOK_TOKEN="hook-token")
    def test_deleting_a_lexware_twin_only_drops_the_clockify_tag(
        self,
        api_client: APIClient,
        workspace: Workspace,
        user: User,
        local_client: Client,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        """The entry exists because Lexware billed it — a Clockify deletion
        must not erase billed history, only the Clockify membership."""
        self._profile(workspace)
        entry = TimeEntry.objects.create(
            workspace=workspace,
            user=user,
            client=local_client,
            started_at=dt.datetime(2026, 7, 1, 7, 0, tzinfo=dt.UTC),
            ended_at=dt.datetime(2026, 7, 1, 9, 30, tzinfo=dt.UTC),
            duration_seconds=9000,
            source=EntrySource.LEXWARE,
            billable=True,
            hourly_rate=Decimal("95.00"),
            computed_amount=Decimal("237.50"),
            billing_status=BillingStatus.BILLED,
        )
        link = link_entry(workspace, entry, "e-9001")

        with django_capture_on_commit_callbacks(execute=True):
            self._post(api_client, "TIME_ENTRY_DELETED", remote_entry(), "hook-token")

        assert TimeEntry.objects.filter(pk=entry.pk).exists()
        assert SyncConflict.objects.count() == 0
        link.refresh_from_db()
        assert link.deleted_remotely is True


class TestSyncTrigger:
    @pytest.fixture(autouse=True)
    def _clockify_on(self) -> Any:
        with override_settings(**CLOCKIFY_ON):
            yield

    @respx.mock
    def test_manual_sync_endpoint_runs_full_sync(
        self, auth_client: APIClient, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        ProviderProfile.objects.create(workspace=workspace, provider=Provider.CLOCKIFY)
        respx.get(f"{WS}/clients").mock(
            return_value=httpx.Response(200, json=[{"id": "c-11", "name": "Acme"}])
        )
        respx.get(f"{WS}/projects").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{WS}/tags").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{WS}/users").mock(
            return_value=httpx.Response(200, json=[{"id": "u-5", "email": "owner@example.com"}])
        )
        respx.get(f"{WS}/user/u-5/time-entries").mock(return_value=httpx.Response(200, json=[]))

        # Eager Celery runs the queued task inline.
        response = auth_client.post(reverse("integrations:sync", args=["clockify"]))
        assert response.status_code == 202
        assert Client.objects.filter(workspace=workspace, name="Acme").exists()

    def test_sync_disabled_is_409(self, auth_client: APIClient) -> None:
        with override_settings(CLOCKIFY_ENABLED=False):
            response = auth_client.post(reverse("integrations:sync", args=["clockify"]))
        assert response.status_code == 409

    def test_sync_requires_admin(self, member_client: APIClient) -> None:
        response = member_client.post(reverse("integrations:sync", args=["clockify"]))
        assert response.status_code == 403


class TestConnectionTest:
    @respx.mock
    @override_settings(**CLOCKIFY_ON)
    def test_connection_test_caches_workspace_and_user(
        self, auth_client: APIClient, workspace: Workspace
    ) -> None:
        respx.get(f"{BASE}/user").mock(
            return_value=httpx.Response(
                200,
                json={"id": "u-5", "name": "Geret", "activeWorkspace": "ws-1"},
            )
        )
        respx.get(f"{BASE}/workspaces").mock(
            return_value=httpx.Response(200, json=[{"id": "ws-1", "name": "Wessling Dev"}])
        )
        response = auth_client.post(reverse("integrations:test", args=["clockify"]))
        assert response.status_code == 200
        assert response.data["company_name"] == "Wessling Dev"

        profile = ProviderProfile.objects.get(workspace=workspace, provider=Provider.CLOCKIFY)
        assert profile.external_organization_id == "ws-1"
        # Load-bearing for the entry push (own user vs. add-time-for-others).
        assert profile.raw_profile["user"]["id"] == "u-5"


class TestLexwareIncrementalSync:
    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key")
    def test_open_invoice_status_and_payment_are_mirrored(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.integrations.lexware.tasks import sync_invoice_statuses
        from apps.invoicing.services import compose_invoice
        from apps.invoicing.tests.test_invoicing import make_entry

        entry = make_entry(workspace, user, local_client, hours=2)
        invoice = compose_invoice(
            workspace=workspace,
            client=local_client,
            entry_ids=[str(entry.pk)],
            grouping="lump_sum",
        )
        invoice.status = InvoiceStatus.DRAFT_REMOTE
        invoice.save(update_fields=["status"])
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="invoice",
            external_id="lex-1",
            local_object_type="invoicing.Invoice",
            local_object_id=invoice.pk,
        )
        respx.get("https://api.lexware.io/v1/invoices/lex-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "lex-1",
                    "voucherStatus": "paid",
                    "voucherNumber": "RE-1007",
                    "version": 3,
                    "totalPrice": {
                        "totalNetAmount": 200.0,
                        "totalTaxAmount": 38.0,
                        "totalGrossAmount": 238.0,
                    },
                },
            )
        )
        respx.get("https://api.lexware.io/v1/payments/lex-1").mock(
            return_value=httpx.Response(
                200,
                json={"paymentStatus": "balanced", "openAmount": 0, "paidDate": "2026-07-15"},
            )
        )

        summary = sync_invoice_statuses(workspace)
        assert summary == {"updated": 1, "deleted_remotely": 0, "failed": 0}

        invoice.refresh_from_db()
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.invoice_number == "RE-1007"
        assert invoice.open_amount == Decimal("0")
        assert invoice.paid_at == dt.date(2026, 7, 15)
        entry.refresh_from_db()
        # Settled invoice settles its entries.
        assert entry.billing_status == BillingStatus.BILLED
