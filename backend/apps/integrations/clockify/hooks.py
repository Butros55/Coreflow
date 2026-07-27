"""On-commit hooks that mirror local time-entry changes to Clockify instantly.

Called from the time-tracking views (create/update/delete/timer-stop) — NOT
from model signals, deliberately: signals would also fire for sync-applied
writes (echo loops) and for cascade deletes (a workspace wipe must never
mass-delete a Clockify account). The sync engine's own writes therefore never
pass through here.

Everything is ``transaction.on_commit`` + Celery: the API response never waits
for Clockify, and a provider outage costs nothing but a skipped mirror that the
periodic sync backfills.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import transaction

if TYPE_CHECKING:
    from apps.timetracking.models import TimeEntry


def schedule_entry_push(entry: TimeEntry) -> None:
    """Mirror a created/edited entry to Clockify after commit."""
    from apps.integrations.clockify.client import is_clockify_enabled

    if not is_clockify_enabled() or entry.ended_at is None:
        return
    workspace_id = str(entry.workspace_id)
    entry_id = str(entry.pk)

    def _enqueue() -> None:
        from apps.integrations.clockify.tasks import push_time_entry

        push_time_entry.delay(workspace_id, entry_id)

    transaction.on_commit(_enqueue)


def schedule_entry_deletion(entry: TimeEntry) -> None:
    """Mirror an entry deletion to Clockify — call BEFORE deleting the entry,
    while its link still exists."""
    from apps.integrations.clockify.client import is_clockify_enabled
    from apps.integrations.models import ExternalObjectLink, Provider

    if not is_clockify_enabled():
        return
    link = ExternalObjectLink.objects.filter(
        workspace=entry.workspace_id,
        provider=Provider.CLOCKIFY,
        resource_type="entry",
        local_object_id=entry.pk,
        deleted_remotely=False,
    ).first()
    if link is None:
        return
    workspace_id = str(entry.workspace_id)
    external_id = link.external_id

    def _enqueue() -> None:
        from apps.integrations.clockify.tasks import delete_time_entry_remote

        delete_time_entry_remote.delay(workspace_id, external_id)

    transaction.on_commit(_enqueue)
