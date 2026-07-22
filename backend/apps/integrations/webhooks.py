"""Inbound webhook receivers.

Persist-then-ack, always: the event row is written first, processing happens in
Celery. Even though Clockify sends the full entity, processing still fetches
current state — a webhook body may be stale by processing time (see the
WebhookEvent docstring).

Clockify (docs/integrations/clockify.md §6):
  * Webhooks are created in the Clockify UI (workspace settings → Webhooks).
    Each webhook subscribes to exactly ONE event type, so several webhooks all
    point at the same URL here.
  * Every delivery carries two headers: ``clockify-webhook-event-type`` (the
    event name, e.g. ``NEW_TIME_ENTRY``) and ``clockify-signature`` (the
    per-webhook signing token shown on creation). Verification is a constant
    time comparison against ``CLOCKIFY_WEBHOOK_TOKEN`` — comma-separated,
    because each webhook has its own token.
  * Delivery guarantees are undocumented → the handler tolerates duplicates
    (dedupe key), gaps (periodic sync backstop) and out-of-order delivery
    (reconciliation always fetches current state).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from rest_framework import status as http_status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.logging import get_logger
from apps.integrations.clockify.mapping import WEBHOOK_EVENT_MAP
from apps.integrations.models import Provider, ProviderProfile, WebhookEvent

logger = get_logger("integrations.webhooks")


def _clockify_workspace() -> Any:
    """The workspace this Clockify account belongs to.

    Credentials are process-global (env), so inbound events attach to the
    workspace that completed the connection test. None ⇒ not connected yet.
    """
    profile = (
        ProviderProfile.objects.filter(provider=Provider.CLOCKIFY)
        .select_related("workspace")
        .first()
    )
    return profile.workspace if profile else None


def _signature_valid(signature: str) -> bool:
    """Compare against every configured token in constant time.

    Clockify issues one signing token PER webhook, and Coreflow needs several
    webhooks (one per event type) — hence a comma-separated list.
    """
    tokens = [t.strip() for t in settings.CLOCKIFY_WEBHOOK_TOKEN.split(",") if t.strip()]
    return any(hmac.compare_digest(signature, token) for token in tokens)


class ClockifyWebhookView(APIView):
    """POST /webhooks/clockify/ — unauthenticated by design, signature-verified."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    # Rate-limited: the endpoint is unauthenticated by nature, so the throttle
    # is the only thing between it and a flood.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    def post(self, request: Request) -> Response:
        if not settings.CLOCKIFY_ENABLED:
            # Disabled integration: nothing here. 404 keeps the surface dark.
            return Response(status=http_status.HTTP_404_NOT_FOUND)

        signature = str(request.headers.get("clockify-signature", ""))
        if not settings.CLOCKIFY_WEBHOOK_TOKEN or not _signature_valid(signature):
            logger.warning("clockify_webhook_bad_signature")
            return Response(status=http_status.HTTP_403_FORBIDDEN)

        workspace = _clockify_workspace()
        if workspace is None:
            # Verified but unattributable — ack so Clockify does not mark the
            # webhook as failing; the periodic sync will pick the change up
            # once the connection test has run.
            logger.warning("clockify_webhook_no_workspace")
            return Response({"ok": True})

        event_name = str(request.headers.get("clockify-webhook-event-type", ""))
        body = request.data if isinstance(request.data, dict) else {}
        external_id = str(body.get("id", ""))

        # Clockify carries no delivery id or timestamp: identical payloads are
        # true replays (safe to drop), changed payloads must process again —
        # so the body digest is part of the identity.
        body_digest = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode()
        ).hexdigest()
        dedupe_key = hashlib.sha256(
            f"{event_name}:{external_id}:{body_digest}".encode()
        ).hexdigest()

        initial_status = "received" if event_name in WEBHOOK_EVENT_MAP else "ignored"
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    workspace=workspace,
                    provider=Provider.CLOCKIFY,
                    event_type=event_name,
                    external_resource_id=external_id,
                    payload=body,
                    dedupe_key=dedupe_key,
                    signature_verified=True,
                    processing_status=initial_status,
                )
        except IntegrityError:
            # Same event delivered twice — the unique dedupe constraint caught
            # it. Ack: processing the first copy is all that matters.
            logger.info("clockify_webhook_duplicate", event_name=event_name, entity_id=external_id)
            return Response({"ok": True, "duplicate": True})

        if initial_status == "received":
            from apps.integrations.clockify.tasks import process_clockify_webhook_event

            transaction.on_commit(lambda: process_clockify_webhook_event.delay(str(event.pk)))
        return Response({"ok": True})
