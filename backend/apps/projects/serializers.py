"""Project & task serializers."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.accounts.serializers import UserSerializer
from apps.core.api import WorkspaceScopedSerializer
from apps.projects.models import (
    Board,
    Project,
    ProjectPhase,
    Sprint,
    Task,
    TaskChecklistItem,
    TaskComment,
    TaskStatus,
)


class ProjectPhaseSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = ProjectPhase
        fields = [
            "id",
            "project",
            "name",
            "order",
            "status",
            "planned_hours",
            "start_date",
            "end_date",
        ]
        read_only_fields = ["id"]


class ProjectSerializer(WorkspaceScopedSerializer):
    lead = UserSerializer(read_only=True)
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    phases = ProjectPhaseSerializer(many=True, read_only=True)
    stats = serializers.SerializerMethodField()
    default_board = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "client",
            "client_name",
            "name",
            "description",
            "status",
            "priority",
            "start_date",
            "target_date",
            "lead",
            "default_hourly_rate",
            "budget_hours",
            "budget_amount",
            "billing_model",
            "progress",
            "tags",
            "color",
            "archived",
            "phases",
            "stats",
            "default_board",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_stats(self, obj: Project) -> dict[str, Any]:
        stats: dict[str, dict[str, Any]] = self.context.get("project_stats", {})
        return stats.get(
            str(obj.pk),
            {
                "open_tasks": 0,
                "done_tasks": 0,
                "logged_seconds": 0,
                "tasks": {},
                "time": {},
                "invoices": {},
            },
        )

    def get_default_board(self, obj: Project) -> str | None:
        boards = getattr(obj, "prefetched_boards", None)
        board = obj.boards.first() if boards is None else (boards[0] if boards else None)
        return str(board.pk) if board else None


class BoardSerializer(WorkspaceScopedSerializer):
    project_name = serializers.CharField(source="project.name", read_only=True)
    client_name = serializers.CharField(source="project.client.display_name", read_only=True)
    project_color = serializers.CharField(source="project.color", read_only=True)

    class Meta:
        model = Board
        fields = [
            "id",
            "project",
            "project_name",
            "client_name",
            "project_color",
            "name",
            "board_type",
            "default_view",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]


class SprintSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = Sprint
        fields = [
            "id",
            "project",
            "board",
            "name",
            "goal",
            "start_date",
            "end_date",
            "status",
            "capacity_hours",
        ]
        read_only_fields = ["id"]


class TaskChecklistItemSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = TaskChecklistItem
        fields = ["id", "task", "title", "done", "order"]
        read_only_fields = ["id"]


class TaskCommentSerializer(WorkspaceScopedSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model = TaskComment
        fields = ["id", "task", "author", "content", "created_at"]
        read_only_fields = ["id", "author", "created_at"]


class TaskSerializer(WorkspaceScopedSerializer):
    assignee_details = UserSerializer(source="assignees", many=True, read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True)
    client_name = serializers.CharField(source="project.client.display_name", read_only=True)
    sprint_name = serializers.CharField(source="sprint.name", read_only=True, default=None)
    phase_name = serializers.CharField(source="phase.name", read_only=True, default=None)
    parent_title = serializers.CharField(source="parent.title", read_only=True, default=None)
    logged_seconds = serializers.IntegerField(read_only=True, default=0)
    checklist_total = serializers.IntegerField(read_only=True, default=0)
    checklist_done = serializers.IntegerField(read_only=True, default=0)
    comment_count = serializers.IntegerField(read_only=True, default=0)
    subtask_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Task
        fields = [
            "id",
            "project",
            "project_name",
            "client_name",
            "phase",
            "phase_name",
            "board",
            "sprint",
            "sprint_name",
            "parent",
            "parent_title",
            "title",
            "description",
            "status",
            "priority",
            "assignees",
            "assignee_details",
            "created_by",
            "start_date",
            "due_date",
            "estimated_hours",
            "billable",
            "tags",
            "order",
            "story_points",
            "progress",
            "archived",
            "logged_seconds",
            "checklist_total",
            "checklist_done",
            "comment_count",
            "subtask_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "order", "created_at", "updated_at"]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Board and project must agree — a task on project A's board that claims
        # project B would corrupt every per-project aggregate.
        board = attrs.get("board") or (self.instance.board if self.instance else None)
        project = attrs.get("project") or (self.instance.project if self.instance else None)
        if board is not None and project is not None and board.project_id != project.pk:
            raise serializers.ValidationError({"board": "Board gehört nicht zu diesem Projekt."})
        sprint = attrs.get("sprint")
        if sprint is not None and project is not None and sprint.project_id != project.pk:
            raise serializers.ValidationError({"sprint": "Sprint gehört nicht zu diesem Projekt."})
        phase = attrs.get("phase")
        if phase is not None and project is not None and phase.project_id != project.pk:
            raise serializers.ValidationError({"phase": "Phase gehört nicht zu diesem Projekt."})

        parent = attrs.get("parent", self.instance.parent if self.instance else None)
        if parent is not None:
            if project is not None and parent.project_id != project.pk:
                raise serializers.ValidationError(
                    {"parent": "Übergeordnete Aufgabe gehört nicht zu diesem Projekt."}
                )
            if board is not None and parent.board_id != board.pk:
                raise serializers.ValidationError(
                    {"parent": "Übergeordnete Aufgabe gehört nicht zu diesem Board."}
                )

            # Reject self-parenting and longer cycles.  The database FK cannot
            # express this graph constraint by itself.
            current: Task | None = parent
            visited: set[Any] = set()
            while current is not None and current.pk not in visited:
                if self.instance is not None and current.pk == self.instance.pk:
                    raise serializers.ValidationError(
                        {"parent": "Unteraufgaben dürfen keinen Zyklus bilden."}
                    )
                visited.add(current.pk)
                current = current.parent
        return attrs


class TaskMoveSerializer(serializers.Serializer[dict[str, Any]]):
    """Input for the kanban move endpoint."""

    status = serializers.ChoiceField(choices=TaskStatus.values)
    # Task id this one should come AFTER within the target column; null = top.
    after = serializers.UUIDField(required=False, allow_null=True)
