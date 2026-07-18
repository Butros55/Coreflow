"""Clockodo sync: mirroring, idempotency, conflicts, webhooks, billed push.

Everything runs against respx mocks — the provider has no sandbox
(docs/integrations/clockodo.md §8) and the autouse ``_no_network`` guard makes a
missed mock a loud failure instead of a live API call.
"""

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
from apps.crm.models import Client
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.clockodo.client import ClockodoClient
from apps.integrations.clockodo.sync import ClockodoSync, push_entries_billed
from apps.integrations.models import (
    ExternalObjectLink,
    Provider,
    ProviderProfile,
    SyncConflict,
    WebhookEvent,
)
from apps.projects.models import Project
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry

pytestmark = pytest.mark.django_db

BASE = "https://my.clockodo.com/api"

CLOCKODO_ON = {
    "CLOCKODO_ENABLED": True,
    "CLOCKODO_API_USER": "me@example.com",
    "CLOCKODO_API_KEY": "secret-key",
    "CLOCKODO_EXTERNAL_APP_EMAIL": "tech@example.com",
}


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


def paged(key: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "paging": {
            "items_per_page": 100,
            "current_page": 1,
            "count_pages": 1,
            "count_items": len(items),
        },
        key: items,
    }


def remote_entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "id": 9001,
        "type": 1,
        "customers_id": 11,
        "projects_id": None,
        "services_id": None,
        "users_id": 5,
        "text": "API-Anbindung",
        "time_since": "2026-07-10T09:00:00Z",
        "time_until": "2026-07-10T11:30:00Z",
        "duration": 9000,
        "billable": 1,
        "hourly_rate": 95,
        "clocked": True,
    }
    entry.update(overrides)
    return entry


def link_customer(workspace: Workspace, local: Client, external_id: int = 11) -> ExternalObjectLink:
    return ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.CLOCKODO,
        resource_type="customer",
        external_id=str(external_id),
        local_object_type="crm.Client",
        local_object_id=local.pk,
    )


def link_user(workspace: Workspace, local: User, external_id: int = 5) -> ExternalObjectLink:
    return ExternalObjectLink.objects.create(
        workspace=workspace,
        provider=Provider.CLOCKODO,
        resource_type="user",
        external_id=str(external_id),
        local_object_type="accounts.User",
        local_object_id=local.pk,
    )


@pytest.fixture
def local_client(workspace: Workspace) -> Client:
    return Client.objects.create(
        workspace=workspace, name="Acme GmbH", default_hourly_rate=Decimal("80.00")
    )


def sync_entries_window(workspace: Workspace, conn: ClockodoClient) -> Any:
    now = timezone.now()
    return ClockodoSync(workspace, trigger="manual").sync_entries(
        conn, since=now - dt.timedelta(days=30), until=now
    )


class TestCustomerSync:
    @pytest.fixture(autouse=True)
    def _clockodo_on(self) -> Any:
        with override_settings(**CLOCKODO_ON):
            yield

    @respx.mock
    def test_remote_customer_becomes_local_mirror(self, workspace: Workspace) -> None:
        respx.get(f"{BASE}/v3/customers").mock(
            return_value=httpx.Response(
                200, json=paged("data", [{"id": 11, "name": "Neukunde AG", "active": True}])
            )
        )
        with ClockodoClient() as conn:
            job = ClockodoSync(workspace).sync_customers(conn)

        created = Client.objects.get(workspace=workspace, name="Neukunde AG")
        link = ExternalObjectLink.objects.get(
            workspace=workspace, provider=Provider.CLOCKODO, resource_type="customer"
        )
        assert link.local_object_id == created.pk
        assert link.external_id == "11"
        assert job.records_created == 1

    @respx.mock
    def test_name_match_links_instead_of_duplicating(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        respx.get(f"{BASE}/v3/customers").mock(
            return_value=httpx.Response(
                200, json=paged("data", [{"id": 11, "name": "acme gmbh", "active": True}])
            )
        )
        with ClockodoClient() as conn:
            ClockodoSync(workspace).sync_customers(conn)

        assert Client.objects.filter(workspace=workspace).count() == 1
        link = ExternalObjectLink.objects.get(
            workspace=workspace, provider=Provider.CLOCKODO, resource_type="customer"
        )
        assert link.local_object_id == local_client.pk

    @respx.mock
    def test_unlinked_local_client_is_pushed(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        respx.get(f"{BASE}/v3/customers").mock(
            return_value=httpx.Response(200, json=paged("data", []))
        )
        create_route = respx.post(f"{BASE}/v3/customers").mock(
            return_value=httpx.Response(
                200, json={"data": {"id": 77, "name": "Acme GmbH", "active": True}}
            )
        )
        with ClockodoClient() as conn:
            job = ClockodoSync(workspace).sync_customers(conn)

        assert create_route.called
        sent = create_route.calls.last.request
        import json

        payload = json.loads(sent.content)
        assert payload["name"] == "Acme GmbH"
        assert payload["billable_default"] is True
        assert ExternalObjectLink.objects.filter(
            workspace=workspace, resource_type="customer", external_id="77"
        ).exists()
        assert job.records_created == 1

    @respx.mock
    def test_second_run_is_a_no_op(self, workspace: Workspace) -> None:
        respx.get(f"{BASE}/v3/customers").mock(
            return_value=httpx.Response(
                200, json=paged("data", [{"id": 11, "name": "Neukunde AG", "active": True}])
            )
        )
        with ClockodoClient() as conn:
            ClockodoSync(workspace).sync_customers(conn)
            job2 = ClockodoSync(workspace).sync_customers(conn)

        assert Client.objects.filter(workspace=workspace).count() == 1
        assert job2.records_created == 0
        assert job2.records_skipped == 1


class TestServiceAndUserSync:
    @pytest.fixture(autouse=True)
    def _clockodo_on(self) -> Any:
        with override_settings(**CLOCKODO_ON):
            yield

    @respx.mock
    def test_service_matches_local_service_type_by_name(self, workspace: Workspace) -> None:
        existing = ServiceType.objects.create(workspace=workspace, name="Entwicklung")
        respx.get(f"{BASE}/v4/services").mock(
            return_value=httpx.Response(
                200, json=paged("data", [{"id": 3, "name": "entwicklung", "active": True}])
            )
        )
        with ClockodoClient() as conn:
            ClockodoSync(workspace).sync_services(conn)

        link = ExternalObjectLink.objects.get(
            workspace=workspace, provider=Provider.CLOCKODO, resource_type="service"
        )
        assert link.local_object_id == existing.pk
        assert ServiceType.objects.filter(workspace=workspace).count() == 1

    @respx.mock
    def test_unlinked_service_type_is_pushed(self, workspace: Workspace) -> None:
        ServiceType.objects.create(workspace=workspace, name="Beratung")
        respx.get(f"{BASE}/v4/services").mock(
            return_value=httpx.Response(200, json=paged("data", []))
        )
        create_route = respx.post(f"{BASE}/v4/services").mock(
            return_value=httpx.Response(
                200, json={"data": {"id": 8, "name": "Beratung", "active": True}}
            )
        )
        with ClockodoClient() as conn:
            ClockodoSync(workspace).sync_services(conn)
        assert create_route.called

    @respx.mock
    def test_users_matched_by_email_only(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        respx.get(f"{BASE}/v3/users").mock(
            return_value=httpx.Response(
                200,
                json=paged(
                    "data",
                    [
                        {"id": 5, "name": "Olive", "email": "OWNER@example.com"},
                        {"id": 6, "name": "Fremd", "email": "stranger@example.com"},
                    ],
                ),
            )
        )
        with ClockodoClient() as conn:
            job = ClockodoSync(workspace).sync_users(conn)

        links = ExternalObjectLink.objects.filter(
            workspace=workspace, provider=Provider.CLOCKODO, resource_type="user"
        )
        assert links.count() == 1
        assert links.get().local_object_id == user.pk
        assert job.records_created == 1
        assert job.records_skipped == 1  # No local account for the stranger.


class TestEntrySync:
    @pytest.fixture(autouse=True)
    def _clockodo_on(self) -> Any:
        with override_settings(**CLOCKODO_ON):
            yield

    def _mock_entries(self, entries: list[dict[str, Any]]) -> None:
        respx.get(f"{BASE}/v2/entries").mock(
            return_value=httpx.Response(200, json=paged("entries", entries))
        )

    @respx.mock
    def test_remote_entry_becomes_time_entry(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])

        with ClockodoClient() as conn:
            job = sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.source == EntrySource.CLOCKODO
        assert entry.user == user
        assert entry.client == local_client
        assert entry.duration_seconds == 9000
        assert entry.description == "API-Anbindung"
        assert entry.hourly_rate == Decimal("95")
        assert entry.computed_amount == Decimal("237.50")  # 2.5h × 95
        assert entry.billing_status == BillingStatus.OPEN
        assert entry.started_at == dt.datetime(2026, 7, 10, 9, 0, tzinfo=dt.UTC)
        assert job.records_created == 1

    @respx.mock
    def test_billable_zero_and_billed_map_to_local_statuses(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries(
            [
                remote_entry(id=1, billable=0),
                remote_entry(id=2, billable=2),
            ]
        )
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        by_external = {
            link.external_id: TimeEntry.objects.get(pk=link.local_object_id)
            for link in ExternalObjectLink.objects.filter(resource_type="entry")
        }
        assert by_external["1"].billing_status == BillingStatus.NOT_BILLABLE
        assert by_external["1"].billable is False
        assert by_external["1"].computed_amount == Decimal("0.00")
        assert by_external["2"].billing_status == BillingStatus.BILLED

    @respx.mock
    def test_running_and_lumpsum_entries_are_skipped(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries(
            [
                remote_entry(id=1, time_until=None, duration=None),  # running clock
                remote_entry(id=2, type=2),  # lumpsum value
            ]
        )
        with ClockodoClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 0
        assert job.records_skipped == 2

    @respx.mock
    def test_unknown_clockodo_user_is_skipped(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        self._mock_entries([remote_entry(users_id=999)])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)
        assert TimeEntry.objects.count() == 0

    @respx.mock
    def test_missing_rate_falls_back_to_local_chain(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry(hourly_rate=None)])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)
        entry = TimeEntry.objects.get()
        # Client default (80.00) wins over the workspace default.
        assert entry.hourly_rate == Decimal("80.00")

    @respx.mock
    def test_second_sync_is_idempotent(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)
            job2 = sync_entries_window(workspace, conn)

        assert TimeEntry.objects.count() == 1
        assert job2.records_created == 0
        assert job2.records_skipped == 1

    @respx.mock
    def test_remote_edit_updates_untouched_local(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        respx.get(f"{BASE}/v2/entries").mock(
            return_value=httpx.Response(
                200,
                json=paged(
                    "entries",
                    [
                        remote_entry(
                            text="Korrigierter Text",
                            duration=10800,
                            time_until="2026-07-10T12:00:00Z",
                        )
                    ],
                ),
            )
        )
        with ClockodoClient() as conn:
            job = sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        assert entry.description == "Korrigierter Text"
        assert entry.duration_seconds == 10800
        assert entry.computed_amount == Decimal("285.00")  # 3h × 95
        assert job.records_updated == 1

    @respx.mock
    def test_local_edit_is_pushed_back_when_remote_unchanged(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        entry.description = "Lokal präzisiert"
        entry.save()

        push_route = respx.put(f"{BASE}/v2/entries/9001").mock(
            return_value=httpx.Response(200, json={"entry": remote_entry(text="Lokal präzisiert")})
        )
        with ClockodoClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert push_route.called
        import json

        assert json.loads(push_route.calls.last.request.content)["text"] == "Lokal präzisiert"
        assert job.records_updated == 1  # counted as pushed
        assert SyncConflict.objects.count() == 0

    @respx.mock
    def test_concurrent_divergence_becomes_conflict(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        entry = TimeEntry.objects.get()
        entry.description = "Lokal geändert"
        entry.save()

        self._mock_entries([remote_entry(text="Remote geändert")])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        conflict = SyncConflict.objects.get()
        assert conflict.reason == "concurrent_modification"
        entry.refresh_from_db()
        # Local version untouched — a human decides.
        assert entry.description == "Lokal geändert"

    @respx.mock
    def test_remote_edit_of_billed_entry_is_a_conflict(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        TimeEntry.objects.update(billing_status=BillingStatus.BILLED)
        self._mock_entries([remote_entry(duration=60, time_until="2026-07-10T09:01:00Z")])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        assert SyncConflict.objects.filter(resource_type="entry").count() == 1
        entry = TimeEntry.objects.get()
        assert entry.duration_seconds == 9000  # untouched

    @respx.mock
    def test_own_billed_push_echo_is_not_a_conflict(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        """After we push billable=2, the next sync sees the changed remote —
        which must be recognised as convergence, not divergence."""
        link_customer(workspace, local_client)
        link_user(workspace, user)
        self._mock_entries([remote_entry()])
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        TimeEntry.objects.update(billing_status=BillingStatus.BILLED)
        self._mock_entries([remote_entry(billable=2)])
        with ClockodoClient() as conn:
            job = sync_entries_window(workspace, conn)

        assert SyncConflict.objects.count() == 0
        assert job.records_skipped == 1  # convergent → unchanged

    @respx.mock
    def test_unlinked_customer_is_fetched_on_demand(
        self, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        """An entry for a never-synced customer pulls that customer mid-flight."""
        link_user(workspace, user)
        self._mock_entries([remote_entry(customers_id=44)])
        respx.get(f"{BASE}/v3/customers/44").mock(
            return_value=httpx.Response(
                200, json={"data": {"id": 44, "name": "Spontan GmbH", "active": True}}
            )
        )
        with ClockodoClient() as conn:
            sync_entries_window(workspace, conn)

        assert Client.objects.filter(workspace=workspace, name="Spontan GmbH").exists()
        assert TimeEntry.objects.count() == 1


class TestBilledPush:
    @pytest.fixture(autouse=True)
    def _clockodo_on(self) -> Any:
        with override_settings(**CLOCKODO_ON):
            yield

    @respx.mock
    def test_only_linked_entries_are_pushed(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.invoicing.tests.test_invoicing import make_entry

        linked = make_entry(workspace, user, local_client, billing_status=BillingStatus.BILLED)
        make_entry(workspace, user, local_client, billing_status=BillingStatus.BILLED)
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            external_id="9001",
            local_object_type="timetracking.TimeEntry",
            local_object_id=linked.pk,
        )
        push_route = respx.put(f"{BASE}/v2/entries/9001").mock(
            return_value=httpx.Response(200, json={"entry": remote_entry(billable=2)})
        )

        pushed = push_entries_billed(workspace, [linked.pk])
        assert pushed == 1
        import json

        assert json.loads(push_route.calls.last.request.content) == {"billable": 2}

    @respx.mock
    def test_mark_entries_billed_enqueues_the_push(
        self,
        workspace: Workspace,
        user: User,
        local_client: Client,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        """The invoicing hook fires the Clockodo mirror task after commit."""
        from apps.invoicing.services import compose_invoice, mark_entries_billed
        from apps.invoicing.tests.test_invoicing import make_entry

        entry = make_entry(workspace, user, local_client, hours=1)
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            external_id="9001",
            local_object_type="timetracking.TimeEntry",
            local_object_id=entry.pk,
        )
        invoice = compose_invoice(
            workspace=workspace,
            client=local_client,
            entry_ids=[str(entry.pk)],
            grouping="lump_sum",
        )
        push_route = respx.put(f"{BASE}/v2/entries/9001").mock(
            return_value=httpx.Response(200, json={"entry": remote_entry(billable=2)})
        )
        with django_capture_on_commit_callbacks(execute=True):
            mark_entries_billed(invoice)

        entry.refresh_from_db()
        assert entry.billing_status == BillingStatus.BILLED
        assert push_route.called


class TestWebhookReceiver:
    URL = "/webhooks/clockodo/"

    def _profile(self, workspace: Workspace) -> ProviderProfile:
        return ProviderProfile.objects.create(
            workspace=workspace, provider=Provider.CLOCKODO, company_name="Testfirma"
        )

    def test_disabled_integration_is_dark(self, api_client: APIClient) -> None:
        response = api_client.post(self.URL, {"token": "x"}, format="json")
        assert response.status_code == 404

    @override_settings(**CLOCKODO_ON, CLOCKODO_WEBHOOK_TOKEN="hook-token")
    def test_handshake_secret_is_persisted_and_surfaced(
        self, api_client: APIClient, auth_client: APIClient, workspace: Workspace
    ) -> None:
        self._profile(workspace)
        response = api_client.post(self.URL, {"secret": "ABCD-1234"}, format="json")
        assert response.status_code == 200

        event = WebhookEvent.objects.get(event_type="webhook.handshake")
        assert event.payload["secret"] == "ABCD-1234"

        status = auth_client.get(reverse("integrations:status"))
        assert status.data["clockodo"]["webhook_handshake_secret"] == "ABCD-1234"
        assert status.data["clockodo"]["webhook_url"].endswith("/webhooks/clockodo/")

    @override_settings(**CLOCKODO_ON, CLOCKODO_WEBHOOK_TOKEN="hook-token")
    def test_bad_token_is_rejected_without_persisting(
        self, api_client: APIClient, workspace: Workspace
    ) -> None:
        self._profile(workspace)
        response = api_client.post(
            self.URL,
            {"event_name": "entry.created", "token": "WRONG", "payload": {"entry": {"id": 1}}},
            format="json",
        )
        assert response.status_code == 403
        assert WebhookEvent.objects.count() == 0

    @respx.mock
    @override_settings(**CLOCKODO_ON, CLOCKODO_WEBHOOK_TOKEN="hook-token")
    def test_entry_created_event_is_fetched_and_mirrored(
        self,
        api_client: APIClient,
        workspace: Workspace,
        user: User,
        local_client: Client,
        django_capture_on_commit_callbacks: Any,
    ) -> None:
        self._profile(workspace)
        link_customer(workspace, local_client)
        link_user(workspace, user)
        respx.get(f"{BASE}/v2/entries/9001").mock(
            return_value=httpx.Response(200, json={"entry": remote_entry()})
        )

        with django_capture_on_commit_callbacks(execute=True):
            response = api_client.post(
                self.URL,
                {
                    "event_name": "entry.created",
                    "token": "hook-token",
                    "occurred_at": "2026-07-10T11:30:05Z",
                    "payload": {"entry": {"id": 9001}},
                },
                format="json",
            )
        assert response.status_code == 200

        event = WebhookEvent.objects.get(event_type="entry.created")
        assert event.processing_status == "processed"
        assert event.signature_verified is True
        assert "token" not in event.payload  # credential never lands in the DB
        entry = TimeEntry.objects.get(workspace=workspace)
        assert entry.source == EntrySource.CLOCKODO

    @override_settings(**CLOCKODO_ON, CLOCKODO_WEBHOOK_TOKEN="hook-token")
    def test_duplicate_delivery_is_deduplicated(
        self, api_client: APIClient, workspace: Workspace
    ) -> None:
        self._profile(workspace)
        body = {
            "event_name": "entry.updated",
            "token": "hook-token",
            "occurred_at": "2026-07-10T11:30:05Z",
            "payload": {"entry": {"id": 9001}},
        }
        first = api_client.post(self.URL, body, format="json")
        second = api_client.post(self.URL, body, format="json")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.data.get("duplicate") is True
        assert WebhookEvent.objects.filter(event_type="entry.updated").count() == 1

    @respx.mock
    @override_settings(**CLOCKODO_ON, CLOCKODO_WEBHOOK_TOKEN="hook-token")
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
        link = ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            external_id="9001",
            local_object_type="timetracking.TimeEntry",
            local_object_id=entry.pk,
        )
        with django_capture_on_commit_callbacks(execute=True):
            api_client.post(
                self.URL,
                {
                    "event_name": "entry.deleted",
                    "token": "hook-token",
                    "occurred_at": "2026-07-11T08:00:00Z",
                    "payload": {"entry": {"id": 9001}},
                },
                format="json",
            )

        assert not TimeEntry.objects.filter(pk=entry.pk).exists()
        link.refresh_from_db()
        assert link.deleted_remotely is True

    @respx.mock
    @override_settings(**CLOCKODO_ON, CLOCKODO_WEBHOOK_TOKEN="hook-token")
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
        ExternalObjectLink.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            resource_type="entry",
            external_id="9001",
            local_object_type="timetracking.TimeEntry",
            local_object_id=entry.pk,
        )
        with django_capture_on_commit_callbacks(execute=True):
            api_client.post(
                self.URL,
                {
                    "event_name": "entry.deleted",
                    "token": "hook-token",
                    "occurred_at": "2026-07-11T08:00:00Z",
                    "payload": {"entry": {"id": 9001}},
                },
                format="json",
            )

        assert TimeEntry.objects.filter(pk=entry.pk).exists()  # never deleted
        conflict = SyncConflict.objects.get()
        assert conflict.reason == "remote_deleted"


class TestSyncTrigger:
    @pytest.fixture(autouse=True)
    def _clockodo_on(self) -> Any:
        with override_settings(**CLOCKODO_ON):
            yield

    @respx.mock
    def test_manual_sync_endpoint_runs_full_sync(
        self, auth_client: APIClient, workspace: Workspace, user: User, owner_membership: Any
    ) -> None:
        ProviderProfile.objects.create(workspace=workspace, provider=Provider.CLOCKODO)
        respx.get(f"{BASE}/v3/customers").mock(
            return_value=httpx.Response(
                200, json=paged("data", [{"id": 11, "name": "Acme", "active": True}])
            )
        )
        respx.get(f"{BASE}/v4/projects").mock(
            return_value=httpx.Response(200, json=paged("data", []))
        )
        respx.get(f"{BASE}/v4/services").mock(
            return_value=httpx.Response(200, json=paged("data", []))
        )
        respx.get(f"{BASE}/v3/users").mock(
            return_value=httpx.Response(
                200, json=paged("data", [{"id": 5, "email": "owner@example.com"}])
            )
        )
        respx.get(f"{BASE}/v2/entries").mock(
            return_value=httpx.Response(200, json=paged("entries", []))
        )

        # Eager Celery runs the queued task inline.
        response = auth_client.post(reverse("integrations:sync", args=["clockodo"]))
        assert response.status_code == 202
        assert Client.objects.filter(workspace=workspace, name="Acme").exists()

    def test_sync_disabled_is_409(self, auth_client: APIClient) -> None:
        with override_settings(CLOCKODO_ENABLED=False):
            response = auth_client.post(reverse("integrations:sync", args=["clockodo"]))
        assert response.status_code == 409

    def test_sync_requires_admin(self, member_client: APIClient) -> None:
        response = member_client.post(reverse("integrations:sync", args=["clockodo"]))
        assert response.status_code == 403


class TestProjectSync:
    @respx.mock
    @override_settings(**CLOCKODO_ON)
    def test_remote_project_mirrors_under_linked_client(
        self, workspace: Workspace, local_client: Client
    ) -> None:
        link_customer(workspace, local_client)
        respx.get(f"{BASE}/v4/projects").mock(
            return_value=httpx.Response(
                200,
                json=paged(
                    "data",
                    [
                        {
                            "id": 21,
                            "customers_id": 11,
                            "name": "Relaunch",
                            "active": True,
                            "completed": False,
                        }
                    ],
                ),
            )
        )
        with ClockodoClient() as conn:
            ClockodoSync(workspace).sync_projects(conn)

        project = Project.objects.get(workspace=workspace, name="Relaunch")
        assert project.client == local_client
        assert ExternalObjectLink.objects.filter(resource_type="project", external_id="21").exists()


class TestLexwareIncrementalSync:
    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="test-key")
    def test_open_invoice_status_and_payment_are_mirrored(
        self, workspace: Workspace, user: User, local_client: Client
    ) -> None:
        from apps.integrations.lexware.tasks import sync_invoice_statuses
        from apps.invoicing.models import InvoiceStatus
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
