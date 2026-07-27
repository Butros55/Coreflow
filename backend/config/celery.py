"""Celery application for Coreflow.

Periodic schedules are declared here but every integration schedule is guarded by
its own ``*_ENABLED`` flag at task runtime, so a disabled provider costs nothing
beyond a no-op tick.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("coreflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.on_after_finalize.connect
def setup_periodic_tasks(sender: Celery, **kwargs: object) -> None:
    """Register periodic syncs.

    Intervals come from settings so they stay configurable via .env. The tasks
    themselves short-circuit when the provider is disabled.
    """
    from django.conf import settings

    sender.add_periodic_task(
        settings.LEXWARE_SYNC_INTERVAL_MINUTES * 60.0,
        app.signature("apps.integrations.lexware.tasks.sync_lexware_incremental"),
        name="lexware:incremental-sync",
    )
    sender.add_periodic_task(
        settings.CLOCKIFY_SYNC_INTERVAL_MINUTES * 60.0,
        app.signature("apps.integrations.clockify.tasks.sync_clockify_incremental"),
        name="clockify:incremental-sync",
    )
    sender.add_periodic_task(
        crontab(minute="*/5"),
        app.signature("apps.integrations.tasks.process_pending_webhook_events"),
        name="webhooks:process-pending",
    )
    # Reserve snapshots are taken on the 1st of each month at 03:00 Europe/Berlin
    # so the finance dashboard can show a real trend line over time.
    sender.add_periodic_task(
        crontab(minute=0, hour=3, day_of_month="1"),
        app.signature("apps.finance.tasks.create_monthly_reserve_snapshot"),
        name="finance:monthly-reserve-snapshot",
    )


@app.task(bind=True, ignore_result=True)
def debug_task(self: object) -> str:
    return "ok"
