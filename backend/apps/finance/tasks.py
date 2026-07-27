"""Finance background tasks."""

from __future__ import annotations

from celery import shared_task

from apps.core.logging import get_logger

logger = get_logger("finance.tasks")


@shared_task(name="apps.finance.tasks.create_monthly_reserve_snapshot")
def create_monthly_reserve_snapshot() -> dict[str, int]:
    """Snapshot every active workspace's reserve, so a trend line accrues.

    Scheduled on the 1st of each month by Celery Beat (config/celery.py).
    """
    from apps.accounts.models import Workspace
    from apps.finance.services import create_snapshot

    created = 0
    failed = 0
    for workspace in Workspace.objects.filter(is_active=True):
        try:
            create_snapshot(workspace)
            created += 1
        except ValueError:
            # No ruleset for the year — skip quietly, it's not an error.
            failed += 1
        except Exception:
            logger.exception("reserve_snapshot_failed", workspace_id=str(workspace.pk))
            failed += 1

    logger.info("monthly_reserve_snapshots", created=created, failed=failed)
    return {"created": created, "failed": failed}
