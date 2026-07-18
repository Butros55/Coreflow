"""Read-only audit log API. Admin+ only; entries are immutable."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from rest_framework import serializers, viewsets

from apps.accounts.permissions import IsWorkspaceAdmin, resolve_workspace
from apps.core.audit import AuditLogEntry


class AuditLogEntrySerializer(serializers.ModelSerializer[AuditLogEntry]):
    actor_email = serializers.EmailField(source="actor.email", read_only=True, default="")

    class Meta:
        model = AuditLogEntry
        fields = [
            "id",
            "created_at",
            "action",
            "actor_email",
            "target_type",
            "target_id",
            "summary",
            "metadata",
            "ip_address",
        ]
        read_only_fields = fields


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet[AuditLogEntry]):
    serializer_class = AuditLogEntrySerializer
    permission_classes = [IsWorkspaceAdmin]

    def get_queryset(self) -> Any:
        workspace = resolve_workspace(self.request)
        if workspace is None:
            return AuditLogEntry.objects.none()
        # Workspace rows, plus global auth events (workspace IS NULL) of this
        # workspace's members — login/logout happen before a workspace header
        # exists, and hiding them would defeat the point of an audit log.
        member_ids = workspace.memberships.values_list("user_id", flat=True)
        qs = AuditLogEntry.objects.filter(
            Q(workspace=workspace) | Q(workspace__isnull=True, actor_id__in=member_ids)
        ).select_related("actor")
        action_prefix = self.request.query_params.get("action")
        if action_prefix:
            qs = qs.filter(action__startswith=action_prefix)
        return qs.order_by("-created_at")
