"""Clockodo ↔ Coreflow payload mapping.

Only verified fields from docs/integrations/clockodo.md are touched. The
normalised projections below are what gets hashed for idempotency — they contain
exactly the fields Coreflow mirrors, so a remote change to a field we ignore
never triggers a write, and a replayed webhook is a guaranteed no-op.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from apps.timetracking.models import BillingStatus

if TYPE_CHECKING:
    from apps.crm.models import Client
    from apps.projects.models import Project
    from apps.timetracking.models import ServiceType, TimeEntry

# EntryV2.type discriminator (clockodo.md §5.4).
ENTRY_TYPE_TIME = 1


def parse_iso_z(value: str) -> dt.datetime:
    """Parse Clockodo's ISO-8601-Z datetimes into aware UTC datetimes."""
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso_z(value: dt.datetime) -> str:
    """Format an aware datetime the way every spec example does: with ``Z``."""
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def entry_is_time_entry(remote: dict[str, Any]) -> bool:
    """Only type-1 time entries map to TimeEntry. Lumpsums (2/3) are money
    without duration — they are counted and skipped, never silently dropped."""
    return int(remote.get("type", ENTRY_TYPE_TIME)) == ENTRY_TYPE_TIME


def entry_is_running(remote: dict[str, Any]) -> bool:
    """Running = null ``time_until`` (clockodo.md §5.4) — not a separate flag."""
    return remote.get("time_until") is None


def billing_status_for(billable: int) -> str:
    """Map ApiEntriesV2_Billability → local billing lifecycle.

    ``2`` (Billed in Clockodo) imports as BILLED so the double-billing guard
    treats it as settled. ``-1`` means "no rights to see it" — imported as OPEN
    because invoice composition is an explicit human selection anyway, and
    hiding the entry entirely would be worse than showing it as open.
    """
    return {
        0: BillingStatus.NOT_BILLABLE,
        1: BillingStatus.OPEN,
        2: BillingStatus.BILLED,
    }.get(int(billable), BillingStatus.OPEN)


def normalize_entry(remote: dict[str, Any]) -> dict[str, Any]:
    """The projection of a remote entry that Coreflow actually mirrors."""
    return {
        "id": remote.get("id"),
        "customers_id": remote.get("customers_id"),
        "projects_id": remote.get("projects_id"),
        "services_id": remote.get("services_id"),
        "users_id": remote.get("users_id"),
        "text": remote.get("text") or "",
        "time_since": remote.get("time_since"),
        "time_until": remote.get("time_until"),
        "duration": remote.get("duration"),
        "billable": remote.get("billable"),
    }


def normalize_customer(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": remote.get("id"),
        "name": remote.get("name"),
        "number": remote.get("number"),
        "active": remote.get("active"),
    }


def normalize_project(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": remote.get("id"),
        "customers_id": remote.get("customers_id"),
        "name": remote.get("name"),
        "number": remote.get("number"),
        "active": remote.get("active"),
        "completed": remote.get("completed"),
    }


def normalize_service(remote: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": remote.get("id"),
        "name": remote.get("name"),
        "active": remote.get("active"),
    }


def remote_hourly_rate(remote: dict[str, Any]) -> Decimal | None:
    """Rate from an enhanced-list entry, or None when absent/no rights.

    ``hourly_rate`` needs both ``enhanced_list=1`` and access rights; a missing
    or non-positive value means "unknown", never 0 (clockodo.md §3) — the local
    rate-resolution chain fills the gap.
    """
    raw = remote.get("hourly_rate")
    if raw is None:
        return None
    try:
        rate = Decimal(str(raw))
    except ArithmeticError:
        return None
    return rate if rate > 0 else None


def customer_payload_from_client(client: Client) -> dict[str, Any]:
    """Outbound create payload. ``number`` is left to Clockodo to assign —
    local client numbers (K-1001 …) live in a different namespace."""
    return {
        "name": client.name,
        "active": not client.archived,
        "billable_default": True,
    }


def project_payload_from_project(project: Project, remote_customer_id: int) -> dict[str, Any]:
    return {
        "name": project.name,
        "customers_id": remote_customer_id,
        "active": not project.archived,
        "billable_default": True,
    }


def service_payload_from_service_type(service_type: ServiceType) -> dict[str, Any]:
    return {
        "name": service_type.name,
        "active": service_type.active,
    }


def entry_update_payload(entry: TimeEntry) -> dict[str, Any]:
    """Outbound push-back of a locally edited, Clockodo-originated entry.

    Only fields the user can edit locally are pushed. IDs (customer/project/
    service) are deliberately not remapped remotely — moving an entry between
    customers is done where it originated.
    """
    payload: dict[str, Any] = {
        "text": entry.description,
        "time_since": iso_z(entry.started_at),
        "billable": 1 if entry.billable else 0,
    }
    if entry.ended_at is not None:
        payload["time_until"] = iso_z(entry.ended_at)
    return payload
