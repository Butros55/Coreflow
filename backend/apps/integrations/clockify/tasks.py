"""Clockify background tasks.

Every task starts with an enabled-check that no-ops when the integration is off
(docs/integrations/clockify.md §1) — a disabled provider costs one early return
per Beat tick, nothing more.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task
from django.utils import timezone

from apps.core.logging import get_logger
from apps.integrations.models import (
    Provider,
    ProviderProfile,
    WebhookEvent,
    WebhookProcessingStatus,
)

logger = get_logger("integrations.clockify.tasks")


def _connected_workspaces() -> list[Any]:
    """Workspaces whose Clockify connection test has succeeded."""
    return [
        profile.workspace
        for profile in ProviderProfile.objects.filter(provider=Provider.CLOCKIFY)
        .select_related("workspace")
        .filter(workspace__is_active=True)
    ]


@shared_task(name="apps.integrations.clockify.tasks.sync_clockify_incremental")
def sync_clockify_incremental() -> dict[str, Any]:
    """Beat: two-way sync of recent work for every connected workspace."""
    from apps.integrations.clockify.client import ClockifyClient, is_clockify_enabled
    from apps.integrations.clockify.sync import ClockifySync

    if not is_clockify_enabled():
        return {"status": "disabled"}

    results: dict[str, str] = {}
    for workspace in _connected_workspaces():
        try:
            with ClockifyClient() as client_conn:
                job = ClockifySync(workspace, trigger="scheduled").incremental_sync(client_conn)
            results[str(workspace.pk)] = job.status
        except Exception as exc:
            logger.exception("clockify_incremental_failed", workspace_id=str(workspace.pk))
            results[str(workspace.pk)] = f"failed: {exc}"
    return {"status": "ok", "workspaces": results}


@shared_task(name="apps.integrations.clockify.tasks.sync_clockify_full")
def sync_clockify_full(workspace_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Manual/connect-time full sync for one workspace."""
    from apps.accounts.models import User, Workspace
    from apps.integrations.clockify.client import ClockifyClient, is_clockify_enabled
    from apps.integrations.clockify.sync import ClockifySync

    if not is_clockify_enabled():
        return {"status": "disabled"}

    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return {"status": "unknown_workspace"}
    user = User.objects.filter(pk=user_id).first() if user_id else None

    with ClockifyClient() as client_conn:
        jobs = ClockifySync(workspace, trigger="manual", triggered_by=user).full_sync(client_conn)
    return {"status": "ok", "jobs": {job.resource_type: job.status for job in jobs}}


@shared_task(
    name="apps.integrations.clockify.tasks.push_entries_billed",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def push_entries_billed(workspace_id: str, entry_ids: list[str]) -> dict[str, Any]:
    """Tag linked entries as billed once a Coreflow invoice is finalised.

    Retried with backoff: billing must never fail because Clockify is down —
    the local status is already settled, this is mirror maintenance. The tag
    write is idempotent (an already-present tag is a no-op).
    """
    from apps.accounts.models import Workspace
    from apps.integrations.clockify.client import is_clockify_enabled
    from apps.integrations.clockify.sync import push_entries_billed as push

    if not is_clockify_enabled():
        return {"status": "disabled"}
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return {"status": "unknown_workspace"}
    pushed = push(workspace, list(entry_ids))
    return {"status": "ok", "pushed": pushed}


@shared_task(name="apps.integrations.clockify.tasks.push_time_entry")
def push_time_entry(workspace_id: str, entry_id: str) -> str:
    """Mirror one locally created/edited entry to Clockify, immediately.

    Enqueued on commit by the time-tracking API. Deliberately NOT retried:
    entry creation is not idempotent (a timeout after the remote write would
    duplicate on retry) — the periodic outbound push is the backstop.
    """
    from apps.accounts.models import Workspace
    from apps.integrations.clockify.client import ClockifyClient, is_clockify_enabled
    from apps.integrations.clockify.sync import ClockifySync
    from apps.timetracking.models import TimeEntry

    if not is_clockify_enabled():
        return "disabled"
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return "unknown_workspace"
    if not ProviderProfile.objects.filter(workspace=workspace, provider=Provider.CLOCKIFY).exists():
        return "not_connected"
    entry = TimeEntry.objects.filter(workspace=workspace, pk=entry_id).first()
    if entry is None or entry.ended_at is None:
        return "skipped"

    try:
        with ClockifyClient() as client_conn:
            outcome = ClockifySync(workspace, trigger="local_change").push_entry(entry, client_conn)
    except Exception:
        logger.exception("clockify_entry_push_failed", entry_id=entry_id)
        return "failed"
    return outcome


@shared_task(
    name="apps.integrations.clockify.tasks.delete_time_entry_remote",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def delete_time_entry_remote(workspace_id: str, external_id: str) -> str:
    """Mirror a local entry deletion to Clockify (DELETE is idempotent)."""
    from apps.accounts.models import Workspace
    from apps.integrations.clockify.client import ClockifyClient, is_clockify_enabled
    from apps.integrations.clockify.sync import ClockifySync

    if not is_clockify_enabled():
        return "disabled"
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return "unknown_workspace"
    with ClockifyClient() as client_conn:
        return ClockifySync(workspace, trigger="local_change").push_entry_deletion(
            external_id, client_conn
        )


@shared_task(name="apps.integrations.clockify.tasks.process_clockify_webhook_event")
def process_clockify_webhook_event(event_id: str) -> str:
    """Fetch-then-reconcile one webhook event (clockify.md §6).

    Idempotent: reconciliation goes through the same hash-guarded appliers as
    the periodic sync, so replays and out-of-order delivery are harmless.
    """
    from apps.integrations.clockify.client import (
        ClockifyClient,
        ClockifyError,
        is_clockify_enabled,
    )
    from apps.integrations.clockify.mapping import WEBHOOK_EVENT_MAP
    from apps.integrations.clockify.sync import ClockifySync
    from apps.integrations.models import ExternalObjectLink
    from apps.timetracking.models import TimeEntry

    event = WebhookEvent.objects.filter(pk=event_id).first()
    if event is None:
        return "missing"
    if event.processing_status == WebhookProcessingStatus.PROCESSED:
        return "already_processed"
    if not is_clockify_enabled():
        event.mark_failed("Integration deaktiviert.")
        return "disabled"

    entity_action = WEBHOOK_EVENT_MAP.get(event.event_type)
    if entity_action is None:
        event.processing_status = WebhookProcessingStatus.IGNORED
        event.processed_at = timezone.now()
        event.save(update_fields=["processing_status", "processed_at", "updated_at"])
        return "ignored"
    entity, action = entity_action

    event.processing_status = WebhookProcessingStatus.PROCESSING
    event.save(update_fields=["processing_status", "updated_at"])

    sync = ClockifySync(event.workspace, trigger="webhook")
    external_id = event.external_resource_id

    try:
        with ClockifyClient() as client_conn:
            if entity == "entry":
                if action == "deleted":
                    link = ExternalObjectLink.objects.filter(
                        workspace=event.workspace,
                        provider=Provider.CLOCKIFY,
                        resource_type="entry",
                        external_id=external_id,
                    ).first()
                    if link is not None:
                        entry = TimeEntry.objects.filter(pk=link.local_object_id).first()
                        sync.handle_entry_deleted(link, entry)
                else:
                    # created/updated/started/stopped all resolve the same way:
                    # fetch current state; a running entry is skipped until it
                    # stops. A 404 means it was deleted meanwhile.
                    try:
                        remote = client_conn.get_time_entry(external_id)
                    except ClockifyError as exc:
                        if exc.status_code == 404:
                            remote = {}
                        else:
                            raise
                    if remote.get("id"):
                        sync.apply_remote_entry(remote, client_conn=client_conn)
                    else:
                        link = ExternalObjectLink.objects.filter(
                            workspace=event.workspace,
                            provider=Provider.CLOCKIFY,
                            resource_type="entry",
                            external_id=external_id,
                        ).first()
                        if link is not None:
                            entry = TimeEntry.objects.filter(pk=link.local_object_id).first()
                            sync.handle_entry_deleted(link, entry)
            elif entity == "client":
                if action == "deleted":
                    sync.mark_link_deleted("client", external_id)
                else:
                    remote = client_conn.get_client(external_id)
                    if remote.get("id"):
                        sync.apply_remote_client(remote)
            elif entity == "project":
                if action == "deleted":
                    sync.mark_link_deleted("project", external_id)
                else:
                    remote = client_conn.get_project(external_id)
                    if remote.get("id"):
                        sync.apply_remote_project(remote)
            elif entity == "tag":
                if action == "deleted":
                    sync.mark_link_deleted("tag", external_id)
                else:
                    # No single-tag GET worth the roundtrip: the webhook body
                    # already carries the tag, and the applier is hash-guarded.
                    payload = event.payload if isinstance(event.payload, dict) else {}
                    if payload.get("id"):
                        sync.apply_remote_tag(payload)
    except Exception as exc:
        logger.exception("clockify_webhook_processing_failed", event_id=str(event.pk))
        event.mark_failed(str(exc))
        return "failed"

    event.mark_processed()
    return "processed"
