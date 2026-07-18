"""Inbound webhook receivers.

Persist-then-ack, always: the event row is written first, processing happens in
Celery. Both providers send pointers, not data — the payload here is evidence,
the API is the source of truth (see WebhookEvent docstring).

Clockodo (docs/integrations/clockodo.md §7):
  * Registration is UI-only. On creation Clockodo POSTs a validation handshake
    ``{"secret": "…"}`` that a HUMAN must paste back into the Clockodo UI — so
    the handshake is persisted and surfaced in the integration centre.
  * Real events carry a plaintext ``token`` (the shared secret configured in
    the UI), compared in constant time. There is no cryptographic signature.
  * Delivery guarantees are undocumented → the handler tolerates duplicates
    (dedupe key), gaps (periodic sync backstop) and out-of-order delivery
    (reconciliation always fetches current state).
"""

from __future__ import annotations

import hashlib
import hmac
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
from apps.integrations.models import Provider, ProviderProfile, WebhookEvent

logger = get_logger("integrations.webhooks")

# The events Coreflow subscribes to (§7.3). Everything else is stored as
# IGNORED — visible in the log, never processed.
CLOCKODO_SUBSCRIBED_EVENTS = frozenset(
    {
        "customer.created",
        "customer.updated",
        "customer.deleted",
        "project.created",
        "project.updated",
        "project.deleted",
        "entry.created",
        "entry.updated",
        "entry.deleted",
        "entry.started",
        "entry.stopped",
    }
)


def _clockodo_workspace() -> Any:
    """The workspace this Clockodo account belongs to.

    Credentials are process-global (env), so inbound events attach to the
    workspace that completed the connection test. None ⇒ not connected yet.
    """
    profile = (
        ProviderProfile.objects.filter(provider=Provider.CLOCKODO)
        .select_related("workspace")
        .first()
    )
    return profile.workspace if profile else None


class ClockodoWebhookView(APIView):
    """POST /webhooks/clockodo/ — unauthenticated by design, token-verified."""

    authentication_classes: list[Any] = []
    permission_classes = [AllowAny]
    # Rate-limited: the endpoint is unauthenticated by nature, so the throttle
    # is the only thing between it and a flood.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "webhook"

    def post(self, request: Request) -> Response:
        if not settings.CLOCKODO_ENABLED:
            # Disabled integration: nothing here. 404 keeps the surface dark.
            return Response(status=http_status.HTTP_404_NOT_FOUND)

        body = request.data if isinstance(request.data, dict) else {}

        # Validation handshake: a lone {"secret": ...} on webhook creation.
        if set(body.keys()) == {"secret"}:
            return self._store_handshake(str(body["secret"]))

        token = str(body.get("token", ""))
        expected = settings.CLOCKODO_WEBHOOK_TOKEN
        if not expected or not hmac.compare_digest(token, expected):
            logger.warning("clockodo_webhook_bad_token")
            return Response(status=http_status.HTTP_403_FORBIDDEN)

        workspace = _clockodo_workspace()
        if workspace is None:
            # Verified but unattributable — ack so Clockodo does not disable
            # the subscription; the payload is a pointer, nothing is lost.
            logger.warning("clockodo_webhook_no_workspace")
            return Response({"ok": True})

        event_name = str(body.get("event_name", ""))
        entity, external_id = self._extract_entity(body)
        occurred_at = str(body.get("occurred_at", ""))
        dedupe_key = hashlib.sha256(
            f"{event_name}:{entity}:{external_id}:{occurred_at}".encode()
        ).hexdigest()

        initial_status = "received" if event_name in CLOCKODO_SUBSCRIBED_EVENTS else "ignored"
        try:
            with transaction.atomic():
                event = WebhookEvent.objects.create(
                    workspace=workspace,
                    provider=Provider.CLOCKODO,
                    event_type=event_name,
                    external_resource_id=external_id,
                    # The token is the credential — it never lands in the DB.
                    payload={k: v for k, v in body.items() if k != "token"},
                    dedupe_key=dedupe_key,
                    signature_verified=True,
                    processing_status=initial_status,
                )
        except IntegrityError:
            # Same event delivered twice — the unique dedupe constraint caught
            # it. Ack: processing the first copy is all that matters.
            logger.info("clockodo_webhook_duplicate", event_name=event_name, entity_id=external_id)
            return Response({"ok": True, "duplicate": True})

        if initial_status == "received":
            from apps.integrations.clockodo.tasks import process_clockodo_webhook_event

            transaction.on_commit(lambda: process_clockodo_webhook_event.delay(str(event.pk)))
        return Response({"ok": True})

    def _store_handshake(self, secret: str) -> Response:
        workspace = _clockodo_workspace()
        if workspace is None:
            # Cannot persist without a workspace; the checklist says to run the
            # connection test first. Ack anyway so the UI flow can continue.
            logger.warning("clockodo_handshake_before_connect")
            return Response({"ok": True})
        WebhookEvent.objects.create(
            workspace=workspace,
            provider=Provider.CLOCKODO,
            event_type="webhook.handshake",
            payload={"secret": secret},
            processing_status="processed",
            signature_verified=False,
        )
        logger.info("clockodo_handshake_stored")
        return Response({"ok": True})

    @staticmethod
    def _extract_entity(body: dict[str, Any]) -> tuple[str, str]:
        """``payload`` is keyed by entity name, each ``{"id": int}`` (§7.2)."""
        payload = body.get("payload")
        if isinstance(payload, dict):
            for entity, value in payload.items():
                if isinstance(value, dict) and value.get("id") is not None:
                    return str(entity), str(value["id"])
        return "", ""
