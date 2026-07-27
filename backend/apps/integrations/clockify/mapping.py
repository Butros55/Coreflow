"""Clockify ↔ Coreflow payload mapping.

The normalised projections below are what gets hashed for idempotency — they
contain exactly the fields Coreflow mirrors, so a remote change to a field we
ignore never triggers a write, and a replayed webhook is a guaranteed no-op.

Semantic mapping:
  * Clockify client   ↔ crm.Client
  * Clockify project  ↔ projects.Project
  * Clockify tag      ↔ timetracking.ServiceType (workspace-global, like tags)
  * Clockify task     ↔ projects.Task (linked lazily, via entries)
  * Clockify time entry ↔ timetracking.TimeEntry

Deliberately NOT mirrored: Clockify hourly rates (their unit is plan-dependent
and often absent) — the local rate-resolution chain prices imported entries.
Clockify also has no "billed" state; billed Coreflow entries are marked with
the :data:`BILLED_TAG_NAME` tag remotely so both sides show the same fact.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from apps.timetracking.models import BillingStatus

if TYPE_CHECKING:
    from apps.crm.models import Client
    from apps.projects.models import Project, Task
    from apps.timetracking.models import ServiceType, TimeEntry

# Workspace tag that marks an entry as billed by Coreflow. Never mapped to a
# local ServiceType; excluded from the tag sync by name.
BILLED_TAG_NAME = "Abgerechnet"

# Clockify webhook event → (entity, action). One webhook subscribes to exactly
# ONE event, so several webhooks (all pointing at the same URL) feed this map;
# events not listed here are stored as IGNORED. Timer events resolve like any
# other entry event: fetch → a still-running entry is skipped until it stops.
WEBHOOK_EVENT_MAP: dict[str, tuple[str, str]] = {
    "NEW_TIME_ENTRY": ("entry", "created"),
    "TIME_ENTRY_UPDATED": ("entry", "updated"),
    "TIME_ENTRY_SPLIT": ("entry", "updated"),
    "TIME_ENTRY_DELETED": ("entry", "deleted"),
    "NEW_TIMER_STARTED": ("entry", "started"),
    "TIMER_STARTED": ("entry", "started"),
    "TIMER_STOPPED": ("entry", "stopped"),
    "NEW_PROJECT": ("project", "created"),
    "PROJECT_UPDATED": ("project", "updated"),
    "PROJECT_DELETED": ("project", "deleted"),
    "NEW_CLIENT": ("client", "created"),
    "CLIENT_UPDATED": ("client", "updated"),
    "CLIENT_DELETED": ("client", "deleted"),
    "NEW_TAG": ("tag", "created"),
    "TAG_UPDATED": ("tag", "updated"),
    "TAG_DELETED": ("tag", "deleted"),
}


def parse_iso_z(value: str) -> dt.datetime:
    """Parse Clockify's ISO-8601 datetimes (``…Z``, optionally fractional)."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_z(value: dt.datetime) -> str:
    """Format an aware datetime the way Clockify expects: UTC with ``Z``."""
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_interval(remote: dict[str, Any]) -> dict[str, Any]:
    return remote.get("timeInterval") or {}


def entry_is_running(remote: dict[str, Any]) -> bool:
    """Running = null ``timeInterval.end`` — Clockify has no separate flag."""
    return not entry_interval(remote).get("end")


def entry_duration_seconds(remote: dict[str, Any]) -> int:
    """Duration from start/end. The ISO-8601 ``duration`` string is redundant
    and occasionally missing, so it is never parsed."""
    interval = entry_interval(remote)
    started = parse_iso_z(str(interval["start"]))
    ended = parse_iso_z(str(interval["end"]))
    return max(int((ended - started).total_seconds()), 0)


def billing_status_for(billable: bool) -> str:
    """Clockify only knows billable yes/no; the billing lifecycle is local."""
    return BillingStatus.OPEN if billable else BillingStatus.NOT_BILLABLE


def normalize_entry(remote: dict[str, Any]) -> dict[str, Any]:
    """The projection of a remote entry that Coreflow actually mirrors."""
    interval = entry_interval(remote)
    return {
        "id": remote.get("id"),
        "userId": remote.get("userId"),
        "projectId": remote.get("projectId"),
        "taskId": remote.get("taskId"),
        "description": remote.get("description") or "",
        "start": interval.get("start"),
        "end": interval.get("end"),
        "billable": bool(remote.get("billable", True)),
        # Sorted: Clockify makes no ordering guarantee and the hash must not care.
        "tagIds": sorted(remote.get("tagIds") or []),
    }


def normalize_client(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": remote.get("id"),
        "name": remote.get("name"),
        "archived": bool(remote.get("archived", False)),
    }


def normalize_project(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": remote.get("id"),
        "clientId": remote.get("clientId") or "",
        "name": remote.get("name"),
        "archived": bool(remote.get("archived", False)),
    }


def normalize_tag(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": remote.get("id"),
        "name": remote.get("name"),
        "archived": bool(remote.get("archived", False)),
    }


def client_payload_from_client(client: Client) -> dict[str, Any]:
    """Outbound create payload. Clockify clients are just a name + note."""
    return {"name": client.name}


def project_payload_from_project(project: Project, remote_client_id: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": project.name,
        "isPublic": True,
        "billable": True,
    }
    if remote_client_id:
        payload["clientId"] = remote_client_id
    if project.color:
        payload["color"] = project.color
    return payload


def tag_payload_from_service_type(service_type: ServiceType) -> dict[str, Any]:
    return {"name": service_type.name}


def task_payload_from_task(task: Task) -> dict[str, Any]:
    return {"name": task.title}


def entry_payload(
    entry: TimeEntry,
    *,
    project_id: str | None,
    task_id: str | None,
    tag_ids: list[str],
) -> dict[str, Any]:
    """Create/update payload for a local entry.

    Used verbatim for POST and PUT — Clockify's PUT *replaces*, so every
    writable field must be present on every update or it would be cleared.
    Running entries never reach this (they are pushed once stopped).
    """
    assert entry.ended_at is not None
    return {
        "start": iso_z(entry.started_at),
        "end": iso_z(entry.ended_at),
        "billable": entry.billable,
        "description": entry.description,
        "projectId": project_id,
        "taskId": task_id,
        "tagIds": tag_ids,
    }
