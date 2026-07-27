"""Provider-agnostic integration tasks."""

from __future__ import annotations

import datetime as dt
from typing import Any

from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from apps.core.logging import get_logger

# Celery's autodiscovery only scans <app>.tasks — the nested provider modules
# must be imported explicitly or the worker never registers their tasks.
from apps.integrations.clockify import tasks as _clockify_tasks  # noqa: F401
from apps.integrations.lexware import tasks as _lexware_tasks  # noqa: F401
from apps.integrations.models import Provider, WebhookEvent, WebhookProcessingStatus

logger = get_logger("integrations.tasks")

MAX_WEBHOOK_RETRIES = 5


@shared_task(name="apps.integrations.tasks.process_pending_webhook_events")
def process_pending_webhook_events() -> dict[str, Any]:
    """Beat backstop: re-dispatch events whose on-commit hook was lost (worker
    restart, crash between persist and enqueue) or whose processing failed.

    Safe to run at any frequency — processing is hash-idempotent.
    """
    from apps.integrations.clockify.tasks import process_clockify_webhook_event

    cutoff = timezone.now() - dt.timedelta(minutes=2)
    stuck = WebhookEvent.objects.filter(
        Q(processing_status=WebhookProcessingStatus.RECEIVED, received_at__lt=cutoff)
        | Q(
            processing_status=WebhookProcessingStatus.FAILED,
            retry_count__lt=MAX_WEBHOOK_RETRIES,
        )
    ).order_by("received_at")[:100]

    dispatched = 0
    for event in stuck:
        if event.provider == Provider.CLOCKIFY:
            process_clockify_webhook_event.delay(str(event.pk))
            dispatched += 1
        # Lexware has no inbound receiver yet; nothing can be stuck for it.

    if dispatched:
        logger.info("webhook_backstop_dispatched", count=dispatched)
    return {"dispatched": dispatched}
