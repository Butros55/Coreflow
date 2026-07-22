"""Integration centre API: status, connection test, sync triggers, conflicts."""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsWorkspaceAdmin, resolve_workspace
from apps.accounts.utils import require_user
from apps.core.audit import record_audit
from apps.core.logging import get_logger
from apps.integrations.models import (
    ConflictResolutionStatus,
    ExternalObjectLink,
    Provider,
    ProviderProfile,
    SyncConflict,
    SyncJob,
    WebhookEvent,
)

logger = get_logger("integrations.views")


def _provider_status(workspace: Any, provider: str) -> dict[str, Any]:
    """Assemble the status card for one provider."""
    if provider == Provider.LEXWARE:
        enabled = settings.LEXWARE_ENABLED
        configured = bool(settings.LEXWARE_API_KEY)
        webhook_configured = bool(settings.LEXWARE_WEBHOOK_SECRET)
    else:
        enabled = settings.CLOCKIFY_ENABLED
        configured = bool(settings.CLOCKIFY_API_KEY)
        webhook_configured = bool(settings.CLOCKIFY_WEBHOOK_TOKEN)

    profile = ProviderProfile.objects.filter(workspace=workspace, provider=provider).first()
    last_success = (
        SyncJob.objects.filter(workspace=workspace, provider=provider, status="success")
        .order_by("-finished_at")
        .first()
    )
    last_failure = (
        SyncJob.objects.filter(workspace=workspace, provider=provider, status="failed")
        .order_by("-finished_at")
        .first()
    )
    open_conflicts = SyncConflict.objects.filter(
        workspace=workspace, provider=provider, resolution_status=ConflictResolutionStatus.OPEN
    ).count()
    linked_objects = ExternalObjectLink.objects.filter(
        workspace=workspace, provider=provider, deleted_remotely=False
    ).count()
    webhook_events = WebhookEvent.objects.filter(workspace=workspace, provider=provider).count()

    extra: dict[str, Any] = {}
    if provider == Provider.CLOCKIFY:
        # Webhook setup is a manual step in Clockify's UI (clockify.md §6):
        # the user creates one webhook PER event type, all pointing at THIS
        # URL, and collects the signing tokens into CLOCKIFY_WEBHOOK_TOKEN.
        extra["webhook_url"] = f"{settings.API_URL.rstrip('/')}/webhooks/clockify/"

    return {
        "provider": provider,
        "enabled": enabled,
        "configured": configured,
        "webhook_configured": webhook_configured,
        **extra,
        "connected": bool(profile and profile.fetched_at),
        "profile": {
            "company_name": profile.company_name if profile else "",
            "organization_id": profile.external_organization_id if profile else "",
            "tax_type": profile.tax_type if profile else "",
            "small_business": profile.small_business if profile else False,
            "subscription_status": profile.subscription_status if profile else "",
            "fetched_at": (
                profile.fetched_at.isoformat() if profile and profile.fetched_at else None
            ),
        }
        if profile
        else None,
        "last_success_at": last_success.finished_at.isoformat()
        if last_success and last_success.finished_at
        else None,
        "last_failure_at": last_failure.finished_at.isoformat()
        if last_failure and last_failure.finished_at
        else None,
        "last_failure_summary": last_failure.error_summary if last_failure else "",
        "open_conflicts": open_conflicts,
        "linked_objects": linked_objects,
        "webhook_events": webhook_events,
    }


class IntegrationStatusView(APIView):
    permission_classes = [IsWorkspaceAdmin]

    def get(self, request: Request) -> Response:
        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        return Response(
            {
                "lexware": _provider_status(workspace, Provider.LEXWARE),
                "clockify": _provider_status(workspace, Provider.CLOCKIFY),
            }
        )


class TestConnectionView(APIView):
    """Test a provider connection and cache its profile on success."""

    permission_classes = [IsWorkspaceAdmin]

    def post(self, request: Request, provider: str) -> Response:
        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)

        if provider in (Provider.LEXWARE, Provider.CLOCKIFY):
            response = (
                self._test_lexware(workspace)
                if provider == Provider.LEXWARE
                else self._test_clockify(workspace)
            )
            record_audit(
                request,
                "integration.connection_tested",
                workspace=workspace,
                summary=f"{provider}: HTTP {response.status_code}",
                provider=provider,
                ok=response.status_code == 200,
            )
            return response
        return Response(
            {"error": {"code": "unknown_provider", "message": "Unbekannter Anbieter."}},
            status=http_status.HTTP_404_NOT_FOUND,
        )

    def _test_lexware(self, workspace: Any) -> Response:
        from apps.integrations.lexware.client import LexwareClient, is_lexware_enabled

        if not is_lexware_enabled():
            return self._disabled("Lexware")
        try:
            with LexwareClient() as client:
                profile = client.get_profile()
        except Exception as exc:
            return self._failed(str(exc))

        ProviderProfile.objects.update_or_create(
            workspace=workspace,
            provider=Provider.LEXWARE,
            defaults={
                "external_organization_id": profile.get("organizationId", ""),
                "connection_id": profile.get("connectionId", ""),
                "company_name": profile.get("companyName", ""),
                "tax_type": profile.get("taxType", ""),
                "small_business": bool(profile.get("smallBusiness", False)),
                "subscription_status": str(profile.get("subscriptionStatus", "")),
                "raw_profile": profile,
                "fetched_at": timezone.now(),
            },
        )
        return Response(
            {
                "ok": True,
                "company_name": profile.get("companyName", ""),
                "tax_type": profile.get("taxType", ""),
            }
        )

    def _test_clockify(self, workspace: Any) -> Response:
        from apps.integrations.clockify.client import ClockifyClient, is_clockify_enabled

        if not is_clockify_enabled():
            return self._disabled("Clockify")
        try:
            with ClockifyClient() as client:
                me = client.get_current_user()
                remote_workspace_id = client.workspace_id
                remote_workspace = next(
                    (
                        w
                        for w in client.list_workspaces()
                        if str(w.get("id")) == remote_workspace_id
                    ),
                    {},
                )
        except Exception as exc:
            return self._failed(str(exc))

        # raw_profile["user"]["id"] is load-bearing: the entry push uses it to
        # decide between "own user" and "add time for others" endpoints.
        company_name = str(remote_workspace.get("name") or me.get("name") or "")
        ProviderProfile.objects.update_or_create(
            workspace=workspace,
            provider=Provider.CLOCKIFY,
            defaults={
                "external_organization_id": remote_workspace_id,
                "company_name": company_name,
                "raw_profile": {"user": me, "workspace": remote_workspace},
                "fetched_at": timezone.now(),
            },
        )
        return Response({"ok": True, "company_name": company_name})

    @staticmethod
    def _disabled(name: str) -> Response:
        return Response(
            {
                "error": {
                    "code": "integration_disabled",
                    "message": f"{name} ist deaktiviert oder ohne Zugangsdaten. "
                    "Aktiviere es zunächst per .env.",
                }
            },
            status=http_status.HTTP_409_CONFLICT,
        )

    @staticmethod
    def _failed(detail: str) -> Response:
        return Response(
            {"error": {"code": "connection_failed", "message": detail}},
            status=http_status.HTTP_502_BAD_GATEWAY,
        )


class TriggerSyncView(APIView):
    """POST /integrations/<provider>/sync — queue a manual sync run.

    Returns 202 immediately; progress lands in SyncJob rows that the status
    card reads. In eager (test) mode the task runs inline.
    """

    permission_classes = [IsWorkspaceAdmin]

    def post(self, request: Request, provider: str) -> Response:
        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)
        user = require_user(request)

        if provider == Provider.CLOCKIFY:
            from apps.integrations.clockify.client import is_clockify_enabled
            from apps.integrations.clockify.tasks import sync_clockify_full

            if not is_clockify_enabled():
                return TestConnectionView._disabled("Clockify")
            sync_clockify_full.delay(str(workspace.pk), str(user.pk))
            record_audit(
                request, "integration.sync_triggered", workspace=workspace, provider=provider
            )
            return Response({"ok": True, "queued": True}, status=http_status.HTTP_202_ACCEPTED)

        if provider == Provider.LEXWARE:
            from apps.integrations.lexware.client import is_lexware_enabled
            from apps.integrations.lexware.tasks import (
                lexware_full_import,
                sync_lexware_incremental,
            )

            if not is_lexware_enabled():
                return TestConnectionView._disabled("Lexware")
            full = bool(request.data.get("full"))
            if full:
                # Full import: all contacts + invoices, idempotent, explicitly
                # confirmed by the user in the UI dialog.
                lexware_full_import.delay(str(workspace.pk), str(user.pk))
            else:
                sync_lexware_incremental.delay()
            record_audit(
                request,
                "integration.sync_triggered",
                workspace=workspace,
                provider=provider,
                mode="full_import" if full else "incremental",
            )
            return Response({"ok": True, "queued": True}, status=http_status.HTTP_202_ACCEPTED)

        return Response(
            {"error": {"code": "unknown_provider", "message": "Unbekannter Anbieter."}},
            status=http_status.HTTP_404_NOT_FOUND,
        )


class SyncConflictSerializer(serializers.ModelSerializer[SyncConflict]):
    class Meta:
        model = SyncConflict
        fields = [
            "id",
            "provider",
            "resource_type",
            "reason",
            "local_snapshot",
            "remote_snapshot",
            "detected_at",
            "resolution_status",
            "external_id",
        ]
        read_only_fields = fields


class SyncConflictViewSet(viewsets.ReadOnlyModelViewSet[SyncConflict]):
    serializer_class = SyncConflictSerializer
    permission_classes = [IsWorkspaceAdmin]

    def get_queryset(self) -> Any:
        workspace = resolve_workspace(self.request)
        if workspace is None:
            return SyncConflict.objects.none()
        qs = SyncConflict.objects.filter(workspace=workspace)
        provider = self.request.query_params.get("provider")
        if provider:
            qs = qs.filter(provider=provider)
        status_filter = self.request.query_params.get("resolution_status", "open")
        if status_filter:
            qs = qs.filter(resolution_status=status_filter)
        return qs.order_by("-detected_at")

    @action(detail=True, methods=["post"])
    def resolve(self, request: Request, pk: str | None = None) -> Response:
        """Resolve a conflict by keeping local, remote, or marking ignored."""
        conflict = self.get_object()
        choice = request.data.get("resolution")
        mapping = {
            "local": ConflictResolutionStatus.RESOLVED_LOCAL,
            "remote": ConflictResolutionStatus.RESOLVED_REMOTE,
            "ignore": ConflictResolutionStatus.IGNORED,
        }
        if choice not in mapping:
            return Response(
                {
                    "error": {
                        "code": "invalid_resolution",
                        "message": "resolution muss local, remote oder ignore sein.",
                    }
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        conflict.resolution_status = mapping[choice]
        conflict.resolved_at = timezone.now()
        conflict.resolved_by = require_user(request)
        conflict.resolution = str(request.data.get("note", ""))
        conflict.save(
            update_fields=[
                "resolution_status",
                "resolved_at",
                "resolved_by",
                "resolution",
                "updated_at",
            ]
        )
        record_audit(
            request,
            "integration.conflict_resolved",
            workspace=conflict.workspace,
            target=conflict,
            summary=f"{conflict.provider}:{conflict.resource_type} → {choice}",
        )
        return Response({"ok": True})
