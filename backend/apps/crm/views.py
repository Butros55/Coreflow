"""CRM API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.db.models import Count, Max, Prefetch, QuerySet, Sum
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.permissions import IsWorkspaceAdmin
from apps.accounts.utils import require_user
from apps.core.api import WorkspaceScopedViewSet
from apps.core.audit import record_audit
from apps.crm.models import (
    ActivityType,
    Client,
    ClientActivity,
    ClientContact,
    ClientNote,
    next_client_number,
)
from apps.crm.privacy import erase_client, export_client_data
from apps.crm.serializers import (
    ClientActivitySerializer,
    ClientContactSerializer,
    ClientNoteSerializer,
    ClientSerializer,
)


class ClientViewSet(WorkspaceScopedViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer
    search_fields = ["name", "short_name", "client_number", "industry", "email"]
    ordering_fields = ["name", "client_number", "status", "customer_since", "created_at"]
    ordering = ["name"]
    filterset_fields = {"status": ["exact"], "archived": ["exact"]}

    def get_queryset(self) -> QuerySet[Any]:
        return (
            super()
            .get_queryset()
            .prefetch_related(
                Prefetch(
                    "contacts",
                    queryset=ClientContact.objects.filter(is_primary=True),
                    to_attr="primary_contacts",
                )
            )
        )

    def get_serializer_context(self) -> dict[str, Any]:
        context = dict(super().get_serializer_context())
        ids = getattr(self, "_stats_client_ids", None)
        if ids:
            context["client_stats"] = self._compute_stats(ids)
        return context

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        # Stash the page's ids so get_serializer_context can batch-load stats.
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        objects: Sequence[Any] = page if page is not None else [*queryset]
        self._stats_client_ids = [obj.pk for obj in objects]
        serializer = self.get_serializer(objects, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        self._stats_client_ids = [instance.pk]
        return Response(self.get_serializer(instance).data)

    def _compute_stats(self, client_ids: Sequence[Any]) -> dict[str, dict[str, Any]]:
        """Three grouped queries for the whole page — correct under multi-joins,
        which per-row multi-Sum annotations are not."""
        from apps.projects.models import Project
        from apps.timetracking.models import BillingStatus, TimeEntry

        stats: dict[str, dict[str, Any]] = {
            str(pk): {
                "active_projects": 0,
                "open_seconds": 0,
                "open_amount": "0.00",
                "last_activity_at": None,
            }
            for pk in client_ids
        }

        projects = (
            Project.objects.filter(client_id__in=client_ids, archived=False, status="active")
            .values("client_id")
            .annotate(n=Count("id"))
        )
        for row in projects:
            stats[str(row["client_id"])]["active_projects"] = row["n"]

        open_time = (
            TimeEntry.objects.filter(
                client_id__in=client_ids,
                billable=True,
                billing_status=BillingStatus.OPEN,
                ended_at__isnull=False,
            )
            .values("client_id")
            .annotate(seconds=Sum("duration_seconds"), amount=Sum("computed_amount"))
        )
        for row in open_time:
            entry = stats[str(row["client_id"])]
            entry["open_seconds"] = row["seconds"] or 0
            entry["open_amount"] = str(row["amount"] or "0.00")

        activity = (
            ClientActivity.objects.filter(client_id__in=client_ids)
            .values("client_id")
            .annotate(last=Max("occurred_at"))
        )
        for row in activity:
            stats[str(row["client_id"])]["last_activity_at"] = (
                row["last"].isoformat() if row["last"] else None
            )

        return stats

    def perform_create(self, serializer: Any) -> None:
        workspace = self.get_workspace()
        assert workspace is not None  # permission layer guarantees membership
        client_number = serializer.validated_data.get("client_number") or next_client_number(
            workspace.pk
        )
        instance = serializer.save(workspace=workspace, client_number=client_number)
        ClientActivity.objects.create(
            workspace=instance.workspace,
            client=instance,
            event_type=ActivityType.CLIENT_CREATED,
            description=f"Kunde „{instance.name}“ angelegt",
            actor=require_user(self.request),
        )

    @action(detail=True, methods=["get"], url_path="export", permission_classes=[IsWorkspaceAdmin])
    def export(self, request: Request, pk: str | None = None) -> Response:
        """Art. 15 DSGVO data export: one JSON bundle of everything stored."""
        client = self.get_object()
        bundle = export_client_data(client)
        record_audit(
            request,
            "privacy.client_exported",
            workspace=client.workspace,
            target=client,
            summary=client.name,
        )
        response = Response(bundle)
        response["Content-Disposition"] = (
            f'attachment; filename="kunde-{client.client_number or client.pk}-export.json"'
        )
        return response

    @action(detail=True, methods=["post"], url_path="erase", permission_classes=[IsWorkspaceAdmin])
    def erase(self, request: Request, pk: str | None = None) -> Response:
        """Art. 17 DSGVO erasure — anonymises under § 147 AO legal hold.

        Requires ``{"confirm": "<exact client name>"}`` so a stray click can
        never destroy data.
        """
        client = self.get_object()
        if str(request.data.get("confirm", "")) != client.name:
            return Response(
                {
                    "error": {
                        "code": "confirmation_mismatch",
                        "message": "Zur Bestätigung den exakten Kundennamen senden.",
                    }
                },
                status=400,
            )
        client_name = client.name
        result = erase_client(client)
        record_audit(
            request,
            "privacy.client_erased" if result["mode"] == "anonymized" else "privacy.client_deleted",
            workspace=self.get_workspace(),
            target_type="crm.Client",
            target_id=result["client_id"],
            summary=client_name,
            mode=result["mode"],
        )
        return Response(result)


class ClientContactViewSet(WorkspaceScopedViewSet):
    queryset = ClientContact.objects.select_related("client")
    serializer_class = ClientContactSerializer
    filterset_fields = {"client": ["exact"], "is_primary": ["exact"]}
    search_fields = ["first_name", "last_name", "email", "position"]
    ordering = ["-is_primary", "last_name"]

    def perform_create(self, serializer: Any) -> None:
        instance = serializer.save(workspace=self.get_workspace())
        ClientActivity.objects.create(
            workspace=instance.workspace,
            client=instance.client,
            event_type=ActivityType.CONTACT_ADDED,
            description=f"Ansprechpartner {instance.full_name} hinzugefügt",
            actor=require_user(self.request),
        )


class ClientNoteViewSet(WorkspaceScopedViewSet):
    queryset = ClientNote.objects.select_related("client", "author")
    serializer_class = ClientNoteSerializer
    filterset_fields = {"client": ["exact"], "note_type": ["exact"]}
    ordering = ["-created_at"]

    def perform_create(self, serializer: Any) -> None:
        instance = serializer.save(
            workspace=self.get_workspace(), author=require_user(self.request)
        )
        ClientActivity.objects.create(
            workspace=instance.workspace,
            client=instance.client,
            event_type=ActivityType.NOTE_ADDED,
            description=f"{instance.get_note_type_display()}: {instance.content[:80]}",
            actor=require_user(self.request),
            note=instance,
        )


class ClientActivityViewSet(WorkspaceScopedViewSet):
    """Read-only: the feed is written by the system, not by clients of the API."""

    queryset = ClientActivity.objects.select_related("actor", "client")
    serializer_class = ClientActivitySerializer
    filterset_fields = {"client": ["exact"], "event_type": ["exact"]}
    ordering = ["-occurred_at"]
    http_method_names = ["get", "head", "options"]
