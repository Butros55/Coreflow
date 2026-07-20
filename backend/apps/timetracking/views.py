"""Time tracking API, including the timer."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import django_filters
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts.utils import require_user
from apps.core.api import WorkspaceScopedViewSet
from apps.core.exceptions import TimerAlreadyRunning
from apps.crm.models import Client
from apps.projects.models import Project, Task
from apps.timetracking.models import EntrySource, ServiceType, TimeEntry
from apps.timetracking.serializers import (
    ServiceTypeSerializer,
    TimeEntrySerializer,
    TimerStartSerializer,
)
from apps.timetracking.services import apply_rounding, compute_amount, resolve_hourly_rate


class ServiceTypeViewSet(WorkspaceScopedViewSet):
    queryset = ServiceType.objects.all()
    serializer_class = ServiceTypeSerializer
    filterset_fields = {"active": ["exact"]}
    ordering = ["name"]


class TimeEntryFilter(django_filters.FilterSet):
    # Half-open interval [from, to) over started_at, sent as ISO datetimes.
    time_from = django_filters.IsoDateTimeFilter(field_name="started_at", lookup_expr="gte")
    time_to = django_filters.IsoDateTimeFilter(field_name="started_at", lookup_expr="lt")

    class Meta:
        model = TimeEntry
        fields = {
            "client": ["exact"],
            "project": ["exact"],
            "task": ["exact"],
            "billable": ["exact"],
            "billing_status": ["exact"],
            "user": ["exact"],
        }


class TimeEntryViewSet(WorkspaceScopedViewSet):
    queryset = TimeEntry.objects.select_related("client", "project", "task", "service_type", "user")
    serializer_class = TimeEntrySerializer
    filterset_class = TimeEntryFilter
    search_fields = ["description", "client__name", "project__name"]
    ordering_fields = ["started_at", "duration_seconds", "computed_amount"]
    ordering = ["-started_at"]
    throttle_scope = "export"

    def extra_create_kwargs(self) -> dict[str, Any]:
        return {"user": require_user(self.request)}

    # --------------------------------------------------------------- exports

    def _export_entries(self) -> list[TimeEntry]:
        """Apply the same filters as the list API and omit running timers."""
        queryset = (
            self.filter_queryset(self.get_queryset())
            .filter(ended_at__isnull=False)
            .order_by("started_at", "created_at")
        )
        return list(queryset)

    def _export_period_label(self, entries: list[TimeEntry]) -> str:
        start = parse_datetime(self.request.query_params.get("time_from", ""))
        end = parse_datetime(self.request.query_params.get("time_to", ""))
        if start and end:
            # The filter is half-open, so the displayed last calendar day is
            # the instant immediately before ``time_to``.
            visible_end = end - timedelta(microseconds=1)
            return (
                f"Zeitraum: {timezone.localtime(start):%d.%m.%Y} – "
                f"{timezone.localtime(visible_end):%d.%m.%Y}"
            )
        if entries:
            return (
                f"Zeitraum: {timezone.localtime(entries[0].started_at):%d.%m.%Y} – "
                f"{timezone.localtime(entries[-1].started_at):%d.%m.%Y}"
            )
        return "Zeitraum: keine abgeschlossenen Einträge"

    def _audit_export(self, request: Request, *, format_name: str, count: int) -> None:
        from apps.core.audit import record_audit

        workspace = self.get_workspace()
        record_audit(
            request,
            "time.exported",
            workspace=workspace,
            target_type="timetracking.TimeEntry",
            summary=f"{count} Zeiteinträge als {format_name.upper()} exportiert",
            format=format_name,
            count=count,
            filters={
                key: value
                for key, value in request.query_params.items()
                if key in {"time_from", "time_to", "client", "project", "billing_status"}
            },
        )

    @action(
        detail=False,
        methods=["get"],
        url_path="export.csv",
        throttle_classes=[ScopedRateThrottle],
    )
    def export_csv(self, request: Request) -> HttpResponse:
        from apps.timetracking.exports import render_timesheet_csv

        entries = self._export_entries()
        content = render_timesheet_csv(entries)
        self._audit_export(request, format_name="csv", count=len(entries))
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="coreflow-zeiterfassung.csv"'
        return response

    @action(
        detail=False,
        methods=["get"],
        url_path="export.pdf",
        throttle_classes=[ScopedRateThrottle],
    )
    def export_pdf(self, request: Request) -> HttpResponse:
        from apps.timetracking.exports import render_timesheet_pdf

        workspace = self.get_workspace()
        assert workspace is not None
        entries = self._export_entries()
        content = render_timesheet_pdf(
            entries,
            workspace=workspace,
            period_label=self._export_period_label(entries),
        )
        self._audit_export(request, format_name="pdf", count=len(entries))
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="coreflow-zeiterfassung.pdf"'
        return response

    # ------------------------------------------------------------------ timer

    @action(detail=False, methods=["get"], url_path="timer")
    def timer(self, request: Request) -> Response:
        """The caller's currently running entry, or null."""
        running = (
            self.get_queryset().filter(user=require_user(request), ended_at__isnull=True).first()
        )
        return Response({"running": self.get_serializer(running).data if running else None})

    @action(detail=False, methods=["post"], url_path="timer/start")
    def start_timer(self, request: Request) -> Response:
        params = TimerStartSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        workspace = self.get_workspace()
        assert workspace is not None

        # Resolve references workspace-scoped; a foreign UUID 404s here.
        task = None
        if data.get("task"):
            task = Task.objects.filter(workspace=workspace, pk=data["task"]).first()
            if task is None:
                return Response(
                    {"error": {"code": "not_found", "message": "Aufgabe nicht gefunden."}},
                    status=http_status.HTTP_404_NOT_FOUND,
                )
        project = None
        if task is not None:
            project = task.project
        elif data.get("project"):
            project = Project.objects.filter(workspace=workspace, pk=data["project"]).first()

        client = None
        if project is not None:
            client = project.client
        elif data.get("client"):
            client = Client.objects.filter(workspace=workspace, pk=data["client"]).first()
        if client is None:
            return Response(
                {
                    "error": {
                        "code": "client_required",
                        "message": "Timer braucht einen Kunden (direkt oder über Projekt/Aufgabe).",
                    }
                },
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        service_type = None
        if data.get("service_type"):
            service_type = ServiceType.objects.filter(
                workspace=workspace, pk=data["service_type"]
            ).first()

        rate = resolve_hourly_rate(
            workspace=workspace, client=client, project=project, service_type=service_type
        )

        try:
            with transaction.atomic():
                entry = TimeEntry.objects.create(
                    workspace=workspace,
                    user=require_user(request),
                    client=client,
                    project=project,
                    task=task,
                    service_type=service_type,
                    description=data.get("description", ""),
                    started_at=timezone.now(),
                    ended_at=None,
                    duration_seconds=0,
                    source=EntrySource.TIMER,
                    billable=data.get("billable", True),
                    hourly_rate=rate,
                )
        except IntegrityError as exc:
            # The partial unique index fired: a timer is already running. This is
            # the race-proof path — the pre-check below is only for a nicer error.
            raise TimerAlreadyRunning from exc

        return Response(self.get_serializer(entry).data, status=http_status.HTTP_201_CREATED)

    @action(detail=False, methods=["post"], url_path="timer/stop")
    def stop_timer(self, request: Request) -> Response:
        workspace = self.get_workspace()
        assert workspace is not None

        with transaction.atomic():
            entry = (
                TimeEntry.objects.select_for_update()
                .filter(workspace=workspace, user=require_user(request), ended_at__isnull=True)
                .first()
            )
            if entry is None:
                return Response(
                    {"error": {"code": "no_running_timer", "message": "Es läuft kein Timer."}},
                    status=http_status.HTTP_404_NOT_FOUND,
                )

            now = timezone.now()
            raw_seconds = max(int((now - entry.started_at).total_seconds()), 1)
            rounded = apply_rounding(
                raw_seconds,
                workspace.time_rounding_increment_minutes,
                workspace.time_rounding_strategy,
            )
            entry.ended_at = entry.started_at + timedelta(seconds=rounded)
            entry.duration_seconds = rounded
            entry.rounded_from_seconds = raw_seconds if rounded != raw_seconds else None
            entry.computed_amount = compute_amount(
                duration_seconds=rounded,
                hourly_rate=entry.hourly_rate,
                billable=entry.billable,
            )
            entry.save(
                update_fields=[
                    "ended_at",
                    "duration_seconds",
                    "rounded_from_seconds",
                    "computed_amount",
                    "updated_at",
                ]
            )

        return Response(self.get_serializer(entry).data)
