"""Sync infrastructure: idempotency and conflict bookkeeping.

The `sync_hash` mechanism is what makes repeated webhooks and overlapping sync
windows safe. Both providers explicitly disclaim exactly-once delivery, so these
guarantees are ours to enforce, not theirs.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import Workspace
from apps.integrations.models import (
    ConflictResolutionStatus,
    ExternalObjectLink,
    Provider,
    SyncConflict,
    SyncJob,
    SyncStatus,
    WebhookEvent,
    WebhookProcessingStatus,
    compute_sync_hash,
)

pytestmark = pytest.mark.django_db


class TestComputeSyncHash:
    def test_is_stable_across_key_order(self) -> None:
        """Providers make no ordering guarantee; the hash must not care."""
        a = {"id": "1", "name": "Acme", "version": 2}
        b = {"version": 2, "name": "Acme", "id": "1"}
        assert compute_sync_hash(a) == compute_sync_hash(b)

    def test_changes_when_a_value_changes(self) -> None:
        a = {"id": "1", "name": "Acme"}
        b = {"id": "1", "name": "Acme GmbH"}
        assert compute_sync_hash(a) != compute_sync_hash(b)

    def test_handles_nested_and_non_json_native_values(self) -> None:
        from datetime import datetime
        from decimal import Decimal

        payload = {
            "id": "1",
            "total": Decimal("119.00"),
            "date": datetime(2024, 3, 1, 12, 0),
            "lines": [{"net": Decimal("100.00")}],
        }
        assert compute_sync_hash(payload).startswith("sha256:")

    def test_distinguishes_null_from_missing(self) -> None:
        assert compute_sync_hash({"a": 1, "b": None}) != compute_sync_hash({"a": 1})


class TestExternalObjectLink:
    def _link(self, workspace: Workspace, **overrides: Any) -> ExternalObjectLink:
        defaults = {
            "workspace": workspace,
            "provider": Provider.LEXWARE,
            "resource_type": "contact",
            "local_object_type": "crm.Client",
            "local_object_id": uuid.uuid4(),
            "external_id": "ext-1",
        }
        return ExternalObjectLink.objects.create(**{**defaults, **overrides})

    def test_same_remote_object_cannot_map_twice_in_one_workspace(
        self, workspace: Workspace
    ) -> None:
        """This constraint is the backbone of webhook idempotency."""
        self._link(workspace)
        with pytest.raises(IntegrityError), transaction.atomic():
            self._link(workspace, local_object_id=uuid.uuid4())

    def test_same_external_id_is_allowed_in_a_different_workspace(
        self, workspace: Workspace, other_workspace: Workspace
    ) -> None:
        self._link(workspace)
        self._link(other_workspace)  # must not raise
        assert ExternalObjectLink.objects.filter(external_id="ext-1").count() == 2

    def test_same_external_id_is_allowed_for_a_different_provider(
        self, workspace: Workspace
    ) -> None:
        self._link(workspace, provider=Provider.LEXWARE)
        self._link(workspace, provider=Provider.CLOCKIFY, resource_type="client")
        assert ExternalObjectLink.objects.count() == 2

    def test_one_local_object_links_once_per_provider_resource(self, workspace: Workspace) -> None:
        local_id = uuid.uuid4()
        self._link(workspace, local_object_id=local_id, external_id="ext-1")
        with pytest.raises(IntegrityError), transaction.atomic():
            self._link(workspace, local_object_id=local_id, external_id="ext-2")

    def test_payload_changed_detects_a_no_op(self, workspace: Workspace) -> None:
        link = self._link(workspace)
        payload = {"id": "ext-1", "name": "Acme", "version": 1}

        assert link.payload_changed(payload) is True  # never synced yet

        link.mark_synced(payload)
        link.refresh_from_db()

        assert link.payload_changed(payload) is False  # replayed webhook → skip
        assert link.payload_changed({**payload, "version": 2}) is True

    def test_mark_synced_records_timestamps(self, workspace: Workspace) -> None:
        from django.utils import timezone

        link = self._link(workspace)
        remote_modified = timezone.now()
        link.mark_synced({"id": "x"}, remote_modified_at=remote_modified)
        link.refresh_from_db()

        assert link.last_synced_at is not None
        assert link.last_remote_modified_at == remote_modified
        assert link.sync_hash.startswith("sha256:")


class TestWebhookEvent:
    def test_dedupe_key_is_unique_per_provider(self, workspace: Workspace) -> None:
        WebhookEvent.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            event_type="invoice.changed",
            external_resource_id="inv-1",
            dedupe_key="abc123",
        )
        with pytest.raises(IntegrityError), transaction.atomic():
            WebhookEvent.objects.create(
                workspace=workspace,
                provider=Provider.LEXWARE,
                event_type="invoice.changed",
                external_resource_id="inv-1",
                dedupe_key="abc123",
            )

    def test_same_dedupe_key_allowed_across_providers(self, workspace: Workspace) -> None:
        for provider in (Provider.LEXWARE, Provider.CLOCKIFY):
            WebhookEvent.objects.create(
                workspace=workspace,
                provider=provider,
                event_type="x.changed",
                dedupe_key="shared-key",
            )
        assert WebhookEvent.objects.count() == 2

    def test_blank_dedupe_keys_do_not_collide(self, workspace: Workspace) -> None:
        """The unique constraint is partial — blank keys must not conflict.

        Otherwise a provider that gives us nothing to dedupe on would be limited
        to a single stored event, ever.
        """
        for i in range(3):
            WebhookEvent.objects.create(
                workspace=workspace,
                provider=Provider.LEXWARE,
                event_type="invoice.changed",
                external_resource_id=f"inv-{i}",
                dedupe_key="",
            )
        assert WebhookEvent.objects.count() == 3

    def test_mark_failed_increments_retry_count(self, workspace: Workspace) -> None:
        event = WebhookEvent.objects.create(
            workspace=workspace, provider=Provider.LEXWARE, event_type="invoice.changed"
        )
        event.mark_failed("boom")
        event.refresh_from_db()
        assert event.processing_status == WebhookProcessingStatus.FAILED
        assert event.retry_count == 1
        assert event.error_message == "boom"

    def test_error_message_is_truncated(self, workspace: Workspace) -> None:
        """Provider error bodies are unbounded; the column is not."""
        event = WebhookEvent.objects.create(
            workspace=workspace, provider=Provider.LEXWARE, event_type="invoice.changed"
        )
        event.mark_failed("x" * 10_000)
        event.refresh_from_db()
        assert len(event.error_message) == 5000


class TestSyncJob:
    def test_lifecycle(self, workspace: Workspace) -> None:
        job = SyncJob.objects.create(
            workspace=workspace, provider=Provider.LEXWARE, resource_type="invoice"
        )
        assert job.status == SyncStatus.PENDING
        assert job.duration_seconds is None

        job.mark_running()
        assert job.status == SyncStatus.RUNNING
        assert job.started_at is not None

        job.mark_finished(SyncStatus.SUCCESS)
        job.refresh_from_db()
        assert job.status == SyncStatus.SUCCESS
        assert job.duration_seconds is not None
        assert job.duration_seconds >= 0


class TestSyncConflict:
    def test_defaults_to_open(self, workspace: Workspace) -> None:
        conflict = SyncConflict.objects.create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            resource_type="contact",
            local_object_type="crm.Client",
            local_snapshot={"name": "Local"},
            remote_snapshot={"name": "Remote"},
        )
        assert conflict.resolution_status == ConflictResolutionStatus.OPEN
        assert conflict.is_open is True

    def test_stores_both_snapshots_for_human_review(self, workspace: Workspace) -> None:
        """No silent data loss: the user must be able to see what diverged."""
        conflict = SyncConflict.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKIFY,
            resource_type="entry",
            local_object_type="timetracking.TimeEntry",
            local_snapshot={"duration": 3600, "text": "Local edit"},
            remote_snapshot={"duration": 7200, "text": "Remote edit"},
            reason="concurrent_modification",
        )
        conflict.refresh_from_db()
        assert conflict.local_snapshot["duration"] == 3600
        assert conflict.remote_snapshot["duration"] == 7200
