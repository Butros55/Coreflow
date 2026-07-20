"""Read-only audit log API. Admin+ only; entries are immutable."""

from __future__ import annotations

from typing import Any

from django.db.models import Q
from rest_framework import serializers, viewsets

from apps.accounts.permissions import IsWorkspaceAdmin, resolve_workspace
from apps.core.audit import AuditLogEntry


class AuditLogEntrySerializer(serializers.ModelSerializer[AuditLogEntry]):
    actor_email = serializers.SerializerMethodField()

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

    def get_actor_email(self, obj: AuditLogEntry) -> str:
        if obj.actor is not None:
            return obj.actor.email
        # Failed login rows deliberately have no actor relation, but can still
        # be attributed to a workspace member by the attempted email address.
        value = obj.metadata.get("email") if isinstance(obj.metadata, dict) else None
        return str(value) if value else ""


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
        member_emails = list(workspace.memberships.values_list("user__email", flat=True))
        qs = AuditLogEntry.objects.filter(
            Q(workspace=workspace)
            | Q(workspace__isnull=True, actor_id__in=member_ids)
            | Q(
                workspace__isnull=True,
                action="auth.login_failed",
                metadata__email__in=member_emails,
            )
        ).select_related("actor")
        action_prefix = self.request.query_params.get("action")
        if action_prefix:
            qs = qs.filter(action__startswith=action_prefix)
        return qs.order_by("-created_at")
