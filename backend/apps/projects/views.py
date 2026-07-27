"""Project & task API, including the kanban move endpoint."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import django_filters
from django.db import transaction
from django.db.models import Count, Prefetch, Q, Sum
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.utils import require_user
from apps.core.api import WorkspaceScopedViewSet
from apps.core.pagination import LargePagination
from apps.crm.models import ActivityType, ClientActivity
from apps.projects.models import (
    ORDER_EPSILON,
    ORDER_STEP,
    Board,
    Project,
    ProjectPhase,
    Sprint,
    Task,
    TaskChecklistItem,
    TaskComment,
)
from apps.projects.serializers import (
    BoardSerializer,
    ProjectPhaseSerializer,
    ProjectSerializer,
    SprintSerializer,
    TaskChecklistItemSerializer,
    TaskCommentSerializer,
    TaskMoveSerializer,
    TaskSerializer,
)


class ProjectViewSet(WorkspaceScopedViewSet):
    queryset = Project.objects.select_related("client", "lead").prefetch_related(
        "phases", Prefetch("boards", to_attr="prefetched_boards")
    )
    serializer_class = ProjectSerializer
    search_fields = ["name", "client__name", "description"]
    ordering_fields = ["name", "status", "target_date", "created_at"]
    ordering = ["name"]
    filterset_fields = {"client": ["exact"], "status": ["exact"], "archived": ["exact"]}

    def get_serializer_context(self) -> dict[str, Any]:
        context = dict(super().get_serializer_context())
        ids = getattr(self, "_stats_ids", None)
        if ids:
            context["project_stats"] = self._compute_stats(ids)
        return context

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        objects: Sequence[Any] = page if page is not None else [*queryset]
        self._stats_ids = [obj.pk for obj in objects]
        serializer = self.get_serializer(objects, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        self._stats_ids = [instance.pk]
        return Response(self.get_serializer(instance).data)

    def _compute_stats(self, ids: Sequence[Any]) -> dict[str, dict[str, Any]]:
        from apps.invoicing.models import Invoice, InvoiceStatus, InvoiceTimeEntry
        from apps.timetracking.models import BillingStatus, TimeEntry

        def empty_stats() -> dict[str, Any]:
            return {
                # Kept for the existing list cards.
                "open_tasks": 0,
                "done_tasks": 0,
                "logged_seconds": 0,
                "tasks": {
                    "total": 0,
                    "open": 0,
                    "done": 0,
                    "overdue": 0,
                    "in_progress": 0,
                    "review": 0,
                    "stuck": 0,
                },
                "time": {
                    "total_seconds": 0,
                    "billable_seconds": 0,
                    "unbilled_seconds": 0,
                    "draft_seconds": 0,
                    "billed_seconds": 0,
                    "paid_seconds": 0,
                    "non_billable_seconds": 0,
                    "total_value": "0.00",
                    "unbilled_value": "0.00",
                    "draft_value": "0.00",
                    "billed_value": "0.00",
                    "paid_value": "0.00",
                },
                "invoices": {
                    "total_count": 0,
                    "draft_count": 0,
                    "open_count": 0,
                    "overdue_count": 0,
                    "paid_count": 0,
                    "invoiced_net": "0.00",
                    "open_gross": "0.00",
                    "paid_net": "0.00",
                },
            }

        stats = {str(pk): empty_stats() for pk in ids}
        today = timezone.localdate()
        tasks = (
            Task.objects.filter(project_id__in=ids, archived=False)
            .values("project_id")
            .annotate(
                total=Count("id"),
                open=Count("id", filter=~Q(status="done")),
                done=Count("id", filter=Q(status="done")),
                overdue=Count("id", filter=Q(due_date__lt=today) & ~Q(status="done")),
                in_progress=Count("id", filter=Q(status="in_progress")),
                review=Count("id", filter=Q(status="review")),
                stuck=Count("id", filter=Q(status="stuck")),
            )
        )
        for row in tasks:
            entry = stats[str(row["project_id"])]
            entry["open_tasks"] = row["open"]
            entry["done_tasks"] = row["done"]
            entry["tasks"] = {key: row[key] for key in entry["tasks"]}
        time = (
            TimeEntry.objects.filter(project_id__in=ids, ended_at__isnull=False)
            .values("project_id")
            .annotate(
                total_seconds=Sum("duration_seconds"),
                billable_seconds=Sum("duration_seconds", filter=Q(billable=True), default=0),
                unbilled_seconds=Sum(
                    "duration_seconds",
                    filter=Q(billing_status__in=[BillingStatus.OPEN, BillingStatus.MARKED]),
                    default=0,
                ),
                draft_seconds=Sum(
                    "duration_seconds",
                    filter=Q(billing_status=BillingStatus.DRAFT_CREATED),
                    default=0,
                ),
                billed_seconds=Sum(
                    "duration_seconds",
                    filter=Q(billing_status=BillingStatus.BILLED),
                    default=0,
                ),
                non_billable_seconds=Sum(
                    "duration_seconds",
                    filter=Q(billing_status=BillingStatus.NOT_BILLABLE),
                    default=0,
                ),
                total_value=Sum("computed_amount", filter=Q(billable=True), default=0),
                unbilled_value=Sum(
                    "computed_amount",
                    filter=Q(billing_status__in=[BillingStatus.OPEN, BillingStatus.MARKED]),
                    default=0,
                ),
                draft_value=Sum(
                    "computed_amount",
                    filter=Q(billing_status=BillingStatus.DRAFT_CREATED),
                    default=0,
                ),
                billed_value=Sum(
                    "computed_amount",
                    filter=Q(billing_status=BillingStatus.BILLED),
                    default=0,
                ),
            )
        )
        for row in time:
            entry = stats[str(row["project_id"])]
            entry["logged_seconds"] = row["total_seconds"] or 0
            for key in (
                "total_seconds",
                "billable_seconds",
                "unbilled_seconds",
                "draft_seconds",
                "billed_seconds",
                "non_billable_seconds",
            ):
                entry["time"][key] = row[key] or 0
            for key in ("total_value", "unbilled_value", "draft_value", "billed_value"):
                entry["time"][key] = str(row[key] or Decimal("0.00"))

        paid_links = (
            InvoiceTimeEntry.objects.filter(
                time_entry__project_id__in=ids,
                invoice__status=InvoiceStatus.PAID,
                invoice_cancelled=False,
            )
            .values("time_entry__project_id")
            .annotate(
                seconds=Sum("duration_seconds_taken"),
                value=Sum("amount_taken"),
            )
        )
        for row in paid_links:
            entry = stats[str(row["time_entry__project_id"])]["time"]
            entry["paid_seconds"] = row["seconds"] or 0
            entry["paid_value"] = str(row["value"] or Decimal("0.00"))

        invoices = (
            Invoice.objects.filter(project_id__in=ids)
            .exclude(status=InvoiceStatus.VOIDED)
            .values("project_id")
            .annotate(
                total_count=Count("id"),
                draft_count=Count(
                    "id",
                    filter=Q(status__in=[InvoiceStatus.DRAFT_LOCAL, InvoiceStatus.DRAFT_REMOTE]),
                ),
                open_count=Count("id", filter=Q(status=InvoiceStatus.OPEN)),
                overdue_count=Count("id", filter=Q(status=InvoiceStatus.OVERDUE)),
                paid_count=Count("id", filter=Q(status=InvoiceStatus.PAID)),
                invoiced_net=Sum(
                    "net_amount",
                    filter=Q(
                        status__in=[
                            InvoiceStatus.OPEN,
                            InvoiceStatus.OVERDUE,
                            InvoiceStatus.PAID,
                        ]
                    ),
                    default=0,
                ),
                open_gross=Sum(
                    "open_amount",
                    filter=Q(status__in=[InvoiceStatus.OPEN, InvoiceStatus.OVERDUE]),
                    default=0,
                ),
                paid_net=Sum("net_amount", filter=Q(status=InvoiceStatus.PAID), default=0),
            )
        )
        for row in invoices:
            invoice_stats = stats[str(row["project_id"])]["invoices"]
            for key in (
                "total_count",
                "draft_count",
                "open_count",
                "overdue_count",
                "paid_count",
            ):
                invoice_stats[key] = row[key]
            for key in ("invoiced_net", "open_gross", "paid_net"):
                invoice_stats[key] = str(row[key] or Decimal("0.00"))
        return stats

    def perform_create(self, serializer: Any) -> None:
        instance = serializer.save(workspace=self.get_workspace())
        # Every project needs a board for its tasks to live on; create the
        # default one server-side so the UI never meets a boardless project.
        Board.objects.create(
            workspace=instance.workspace,
            project=instance,
            name="Hauptboard",
        )
        ClientActivity.objects.create(
            workspace=instance.workspace,
            client=instance.client,
            event_type=ActivityType.PROJECT_CREATED,
            description=f"Projekt „{instance.name}“ angelegt",
            actor=require_user(self.request),
            project=instance,
        )


class ProjectPhaseViewSet(WorkspaceScopedViewSet):
    queryset = ProjectPhase.objects.select_related("project")
    serializer_class = ProjectPhaseSerializer
    filterset_fields = {"project": ["exact"], "status": ["exact"]}
    ordering = ["order"]


class BoardViewSet(WorkspaceScopedViewSet):
    queryset = Board.objects.select_related("project", "project__client")
    serializer_class = BoardSerializer
    filterset_fields = {"project": ["exact"]}
    search_fields = ["name", "project__name"]
    ordering = ["project__name", "name"]


class SprintViewSet(WorkspaceScopedViewSet):
    queryset = Sprint.objects.select_related("project")
    serializer_class = SprintSerializer
    filterset_fields = {"project": ["exact"], "board": ["exact"], "status": ["exact"]}
    ordering = ["-start_date"]


class TaskFilter(django_filters.FilterSet):
    assigned_to_me = django_filters.BooleanFilter(method="filter_assigned_to_me")
    client = django_filters.UUIDFilter(field_name="project__client_id")

    class Meta:
        model = Task
        fields = {
            "board": ["exact"],
            "project": ["exact"],
            "sprint": ["exact"],
            "status": ["exact"],
            "priority": ["exact"],
            "archived": ["exact"],
            "parent": ["exact", "isnull"],
        }

    def filter_assigned_to_me(self, queryset: Any, name: str, value: bool) -> Any:
        if value and self.request is not None:
            return queryset.filter(assignees=self.request.user)
        return queryset


class TaskViewSet(WorkspaceScopedViewSet):
    queryset = (
        Task.objects.select_related("project", "project__client", "sprint", "phase", "parent")
        .prefetch_related("assignees")
        .annotate(
            logged_seconds=Sum("time_entries__duration_seconds", default=0),
            checklist_total=Count("checklist", distinct=True),
            checklist_done=Count("checklist", filter=Q(checklist__done=True), distinct=True),
            comment_count=Count("comments", distinct=True),
            subtask_count=Count("subtasks", distinct=True),
        )
    )
    serializer_class = TaskSerializer
    # Boards legitimately need a full column set at once.
    pagination_class = LargePagination
    filterset_class = TaskFilter
    search_fields = ["title", "description", "project__name"]
    ordering_fields = ["order", "due_date", "priority", "created_at", "title"]
    ordering = ["status", "order", "created_at"]

    def extra_create_kwargs(self) -> dict[str, Any]:
        return {"created_by": require_user(self.request)}

    def perform_create(self, serializer: Any) -> None:
        # Append to the bottom of the target column.
        board = serializer.validated_data.get("board")
        target_status = serializer.validated_data.get("status", "todo")
        last = (
            Task.objects.filter(board=board, status=target_status)
            .order_by("-order")
            .values_list("order", flat=True)
            .first()
        )
        next_order = (last or Decimal(0)) + ORDER_STEP
        serializer.save(
            workspace=self.get_workspace(),
            created_by=require_user(self.request),
            order=next_order,
        )

    def perform_update(self, serializer: Any) -> None:
        previous_status = serializer.instance.status
        instance = serializer.save()
        if previous_status != "done" and instance.status == "done":
            ClientActivity.objects.create(
                workspace=instance.workspace,
                client=instance.project.client,
                event_type=ActivityType.TASK_COMPLETED,
                description=f"Aufgabe „{instance.title}“ abgeschlossen",
                actor=require_user(self.request),
                project=instance.project,
            )

    @action(detail=True, methods=["post"])
    def move(self, request: Request, pk: str | None = None) -> Response:
        """Kanban drag-and-drop: place the task after a sibling in a column.

        The whole operation is one row's UPDATE thanks to fractional ranking;
        the transaction + row locks exist for the rare rebalance path and to
        serialise concurrent moves within one column.
        """
        serializer = TaskMoveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_status: str = serializer.validated_data["status"]
        after_id = serializer.validated_data.get("after")

        with transaction.atomic():
            # get_object() 404s workspace-scoped; the lock must then use the
            # PLAIN queryset — the annotated one carries a GROUP BY, and
            # Postgres refuses FOR UPDATE combined with GROUP BY.
            task = Task.objects.select_for_update().get(pk=self.get_object().pk)
            siblings = list(
                Task.objects.select_for_update()
                .filter(board_id=task.board_id, status=target_status, archived=False)
                .exclude(pk=task.pk)
                .order_by("order")
            )

            after_task = None
            if after_id is not None:
                after_task = next((s for s in siblings if s.pk == after_id), None)
                if after_task is None:
                    return Response(
                        {
                            "error": {
                                "code": "invalid_anchor",
                                "message": "Anker-Aufgabe nicht in dieser Spalte.",
                            }
                        },
                        status=http_status.HTTP_400_BAD_REQUEST,
                    )

            new_order = self._compute_order(siblings, after_task)
            if new_order is None:
                # Gap exhausted: renumber the column, then place again.
                for index, sibling in enumerate(siblings):
                    sibling.order = ORDER_STEP * (index + 1)
                Task.objects.bulk_update(siblings, ["order"])
                new_order = self._compute_order(siblings, after_task)
                assert new_order is not None

            task.status = target_status
            task.order = new_order
            task.save(update_fields=["status", "order", "updated_at"])

        refreshed = self.get_queryset().get(pk=task.pk)
        return Response(TaskSerializer(refreshed, context=self.get_serializer_context()).data)

    @staticmethod
    def _compute_order(siblings: list[Task], after_task: Task | None) -> Decimal | None:
        """Midpoint order for a placement; None when the gap is too small."""
        if not siblings:
            return ORDER_STEP
        if after_task is None:  # top of column
            first = siblings[0].order
            candidate = first / 2
            return candidate if first - candidate > ORDER_EPSILON else None
        index = siblings.index(after_task)
        lower = after_task.order
        if index == len(siblings) - 1:  # bottom
            return lower + ORDER_STEP
        upper = siblings[index + 1].order
        candidate = (lower + upper) / 2
        if candidate - lower <= ORDER_EPSILON or upper - candidate <= ORDER_EPSILON:
            return None
        return candidate


class TaskCommentViewSet(WorkspaceScopedViewSet):
    queryset = TaskComment.objects.select_related("author", "task")
    serializer_class = TaskCommentSerializer
    filterset_fields = {"task": ["exact"]}
    ordering = ["created_at"]

    def extra_create_kwargs(self) -> dict[str, Any]:
        return {"author": require_user(self.request)}


class TaskChecklistItemViewSet(WorkspaceScopedViewSet):
    queryset = TaskChecklistItem.objects.select_related("task")
    serializer_class = TaskChecklistItemSerializer
    filterset_fields = {"task": ["exact"]}
    ordering = ["order", "created_at"]
