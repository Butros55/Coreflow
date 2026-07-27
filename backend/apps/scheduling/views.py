"""Appointment API + ICS export/import + create-task-from-appointment."""

from __future__ import annotations

from typing import Any

import django_filters
from django.http import HttpResponse
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.utils import require_user
from apps.core.api import WorkspaceScopedViewSet
from apps.scheduling.ics import appointments_to_ics, parse_ics
from apps.scheduling.models import Appointment
from apps.scheduling.serializers import AppointmentSerializer


class AppointmentFilter(django_filters.FilterSet):
    from_date = django_filters.IsoDateTimeFilter(field_name="starts_at", lookup_expr="gte")
    to_date = django_filters.IsoDateTimeFilter(field_name="starts_at", lookup_expr="lt")

    class Meta:
        model = Appointment
        fields = {"client": ["exact"], "project": ["exact"], "status": ["exact"]}


class AppointmentViewSet(WorkspaceScopedViewSet):
    queryset = Appointment.objects.select_related("client", "project").prefetch_related(
        "participants"
    )
    serializer_class = AppointmentSerializer
    filterset_class = AppointmentFilter
    search_fields = ["title", "description", "location"]
    ordering_fields = ["starts_at", "created_at"]
    ordering = ["starts_at"]

    def perform_create(self, serializer: Any) -> None:
        instance = serializer.save(workspace=self.get_workspace())
        # Auto-add the creator as a participant if none given.
        if not instance.participants.exists():
            instance.participants.add(require_user(self.request))

    @action(detail=False, methods=["get"], url_path="export.ics")
    def export_ics(self, request: Request) -> HttpResponse:
        """Export the (filtered) appointments as an ICS file."""
        queryset = self.filter_queryset(self.get_queryset())
        content = appointments_to_ics(list(queryset))
        response = HttpResponse(content, content_type="text/calendar; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="coreflow-termine.ics"'
        return response

    @action(detail=False, methods=["post"], url_path="import-ics")
    def import_ics(self, request: Request) -> Response:
        """Import appointments from an uploaded ICS file. Idempotent by ics_uid."""
        workspace = self.get_workspace()
        assert workspace is not None
        raw = request.data.get("ics") or (
            request.FILES["file"].read().decode("utf-8") if "file" in request.FILES else None
        )
        if not raw:
            return Response(
                {"error": {"code": "no_ics", "message": "Keine ICS-Daten übermittelt."}},
                status=http_status.HTTP_400_BAD_REQUEST,
            )
        created, updated = 0, 0
        for event in parse_ics(raw):
            _, was_created = Appointment.objects.update_or_create(
                workspace=workspace,
                ics_uid=event["uid"],
                defaults={
                    "title": event["title"],
                    "description": event.get("description", ""),
                    "starts_at": event["starts_at"],
                    "ends_at": event["ends_at"],
                    "location": event.get("location", ""),
                },
            )
            created += int(was_created)
            updated += int(not was_created)
        return Response({"created": created, "updated": updated})

    @action(detail=True, methods=["post"], url_path="create-task")
    def create_task(self, request: Request, pk: str | None = None) -> Response:
        """Create a follow-up task from this appointment's next steps."""
        from apps.projects.models import Board, Task

        appointment = self.get_object()
        if appointment.project is None:
            return Response(
                {
                    "error": {
                        "code": "no_project",
                        "message": "Termin ist keinem Projekt zugeordnet.",
                    }
                },
                status=http_status.HTTP_409_CONFLICT,
            )
        board = Board.objects.filter(project=appointment.project).first()
        if board is None:
            return Response(
                {"error": {"code": "no_board", "message": "Projekt hat kein Board."}},
                status=http_status.HTTP_409_CONFLICT,
            )
        title = request.data.get("title") or f"Nachfassen: {appointment.title}"
        task = Task.objects.create(
            workspace=appointment.workspace,
            project=appointment.project,
            board=board,
            title=title,
            description=appointment.next_steps or appointment.outcome_notes,
            created_by=require_user(request),
        )
        task.assignees.add(require_user(request))
        return Response({"task_id": str(task.id), "board_id": str(board.id)})
