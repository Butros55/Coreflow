"""Time-entry domain logic: rate resolution, rounding, amount computation.

Kept out of views and serializers so the timer endpoints, manual entry, the
future Clockodo import and tests all share exactly one implementation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from apps.core.money import line_amount

if TYPE_CHECKING:
    from apps.accounts.models import Workspace
    from apps.crm.models import Client
    from apps.projects.models import Project
    from apps.timetracking.models import ServiceType


def resolve_hourly_rate(
    *,
    workspace: Workspace,
    client: Client | None,
    project: Project | None,
    service_type: ServiceType | None,
    explicit: Decimal | None = None,
) -> Decimal:
    """Most specific rate wins: explicit > project > client > service type > workspace.

    The result is SNAPSHOTTED onto the entry — later rate changes must never
    reprice already-tracked work.
    """
    if explicit is not None:
        return explicit
    if project is not None and project.default_hourly_rate is not None:
        return project.default_hourly_rate
    if client is not None and client.default_hourly_rate is not None:
        return client.default_hourly_rate
    if service_type is not None and service_type.default_hourly_rate is not None:
        return service_type.default_hourly_rate
    return workspace.default_hourly_rate


def apply_rounding(seconds: int, increment_minutes: int, strategy: str) -> int:
    """Round a duration to the workspace's increment. 0 ⇒ no rounding.

    Only ever applied when the timer STOPS (or a manual entry is created), and
    the pre-rounding value is preserved on the entry — rounding must be
    auditable, not silent.
    """
    if increment_minutes <= 0 or seconds <= 0:
        return seconds
    step = increment_minutes * 60
    full_steps, remainder = divmod(seconds, step)
    if remainder == 0:
        return seconds
    if strategy == "up":
        return (full_steps + 1) * step
    if strategy == "down":
        # A worked entry must not round to zero — the minimum is one increment.
        return max(full_steps, 1) * step
    # nearest (default); exact half rounds up, matching commercial practice
    if remainder * 2 >= step:
        return (full_steps + 1) * step
    return max(full_steps, 1) * step if full_steps == 0 else full_steps * step


def compute_amount(*, duration_seconds: int, hourly_rate: Decimal, billable: bool) -> Decimal:
    """Monetary value of an entry. Non-billable work is worth 0 by definition."""
    if not billable or duration_seconds <= 0:
        return Decimal("0.00")
    return line_amount(duration_seconds, hourly_rate)
