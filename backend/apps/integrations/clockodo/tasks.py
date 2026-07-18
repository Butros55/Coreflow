"""Clockodo background tasks.

Every task starts with an enabled-check that no-ops when the integration is off
(docs/integrations/clockodo.md §1) — a disabled provider costs one early return
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

logger = get_logger("integrations.clockodo.tasks")


def _connected_workspaces() -> list[Any]:
    """Workspaces whose Clockodo connection test has succeeded."""
    return [
        profile.workspace
        for profile in ProviderProfile.objects.filter(provider=Provider.CLOCKODO)
        .select_related("workspace")
        .filter(workspace__is_active=True)
    ]


@shared_task(name="apps.integrations.clockodo.tasks.sync_clockodo_incremental")
def sync_clockodo_incremental() -> dict[str, Any]:
    """Beat: windowed entry sync for every connected workspace."""
    from apps.integrations.clockodo.client import ClockodoClient, is_clockodo_enabled
    from apps.integrations.clockodo.sync import ClockodoSync

    if not is_clockodo_enabled():
        return {"status": "disabled"}

    results: dict[str, str] = {}
    for workspace in _connected_workspaces():
        try:
            with ClockodoClient() as client_conn:
                job = ClockodoSync(workspace, trigger="scheduled").incremental_sync(client_conn)
            results[str(workspace.pk)] = job.status
        except Exception as exc:
            logger.exception("clockodo_incremental_failed", workspace_id=str(workspace.pk))
            results[str(workspace.pk)] = f"failed: {exc}"
    return {"status": "ok", "workspaces": results}


@shared_task(name="apps.integrations.clockodo.tasks.sync_clockodo_full")
def sync_clockodo_full(workspace_id: str, user_id: str | None = None) -> dict[str, Any]:
    """Manual/connect-time full sync for one workspace."""
    from apps.accounts.models import User, Workspace
    from apps.integrations.clockodo.client import ClockodoClient, is_clockodo_enabled
    from apps.integrations.clockodo.sync import ClockodoSync

    if not is_clockodo_enabled():
        return {"status": "disabled"}

    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return {"status": "unknown_workspace"}
    user = User.objects.filter(pk=user_id).first() if user_id else None

    with ClockodoClient() as client_conn:
        jobs = ClockodoSync(workspace, trigger="manual", triggered_by=user).full_sync(client_conn)
    return {"status": "ok", "jobs": {job.resource_type: job.status for job in jobs}}


@shared_task(
    name="apps.integrations.clockodo.tasks.push_entries_billed",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def push_entries_billed(workspace_id: str, entry_ids: list[str]) -> dict[str, Any]:
    """PUT billable=2 for linked entries once a Coreflow invoice is billed.

    Retried with backoff: billing must never fail because Clockodo is down —
    the local status is already settled, this is mirror maintenance.
    """
    from apps.accounts.models import Workspace
    from apps.integrations.clockodo.client import is_clockodo_enabled
    from apps.integrations.clockodo.sync import push_entries_billed as push

    if not is_clockodo_enabled():
        return {"status": "disabled"}
    workspace = Workspace.objects.filter(pk=workspace_id).first()
    if workspace is None:
        return {"status": "unknown_workspace"}
    pushed = push(workspace, list(entry_ids))
    return {"status": "ok", "pushed": pushed}


@shared_task(name="apps.integrations.clockodo.tasks.process_clockodo_webhook_event")
def process_clockodo_webhook_event(event_id: str) -> str:
    """Fetch-then-reconcile one webhook pointer (clockodo.md §7.2).

    Idempotent: reconciliation goes through the same hash-guarded appliers as
    the periodic sync, so replays and out-of-order delivery are harmless.
    """
    from apps.integrations.clockodo.client import (
        ClockodoClient,
        ClockodoError,
        is_clockodo_enabled,
    )
    from apps.integrations.clockodo.sync import ClockodoSync
    from apps.integrations.models import ExternalObjectLink
    from apps.timetracking.models import TimeEntry

    event = WebhookEvent.objects.filter(pk=event_id).first()
    if event is None:
        return "missing"
    if event.processing_status == WebhookProcessingStatus.PROCESSED:
        return "already_processed"
    if not is_clockodo_enabled():
        event.mark_failed("Integration deaktiviert.")
        return "disabled"

    event.processing_status = WebhookProcessingStatus.PROCESSING
    event.save(update_fields=["processing_status", "updated_at"])

    sync = ClockodoSync(event.workspace, trigger="webhook")
    entity = event.event_type.split(".", 1)[0]
    action = event.event_type.split(".", 1)[-1]
    external_id = event.external_resource_id

    try:
        with ClockodoClient() as client_conn:
            if entity == "entry":
                if action == "deleted":
                    link = ExternalObjectLink.objects.filter(
                        workspace=event.workspace,
                        provider=Provider.CLOCKODO,
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
                        remote = client_conn.get_entry(int(external_id)).get("entry") or {}
                    except ClockodoError as exc:
                        if exc.status_code == 404:
                            remote = {}
                        else:
                            raise
                    if remote:
                        sync.apply_remote_entry(remote, client_conn=client_conn)
                    else:
                        link = ExternalObjectLink.objects.filter(
                            workspace=event.workspace,
                            provider=Provider.CLOCKODO,
                            resource_type="entry",
                            external_id=external_id,
                        ).first()
                        if link is not None:
                            entry = TimeEntry.objects.filter(pk=link.local_object_id).first()
                            sync.handle_entry_deleted(link, entry)
            elif entity == "customer":
                if action == "deleted":
                    sync.mark_link_deleted("customer", external_id)
                else:
                    remote = client_conn.get_customer(int(external_id)).get("data") or {}
                    if remote:
                        sync.apply_remote_customer(remote)
            elif entity == "project":
                if action == "deleted":
                    sync.mark_link_deleted("project", external_id)
                else:
                    remote = client_conn.get_project(int(external_id)).get("data") or {}
                    if remote:
                        sync.apply_remote_project(remote)
            else:
                event.processing_status = WebhookProcessingStatus.IGNORED
                event.processed_at = timezone.now()
                event.save(update_fields=["processing_status", "processed_at", "updated_at"])
                return "ignored"
    except Exception as exc:
        logger.exception("clockodo_webhook_processing_failed", event_id=str(event.pk))
        event.mark_failed(str(exc))
        return "failed"

    event.mark_processed()
    return "processed"
