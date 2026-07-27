"""Projects, phases, boards, sprints and tasks."""

from __future__ import annotations

from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel

# Spacing between freshly appended tasks. Wide enough that midpoint insertion
# can halve the gap ~40 times before a rebalance is needed.
ORDER_STEP = Decimal("1024")
# Below this gap, neighbouring orders are too close to midpoint reliably and the
# column gets renumbered.
ORDER_EPSILON = Decimal("0.000001")


class ProjectStatus(models.TextChoices):
    PLANNED = "planned", _("Geplant")
    ACTIVE = "active", _("Aktiv")
    ON_HOLD = "on_hold", _("Pausiert")
    COMPLETED = "completed", _("Abgeschlossen")
    CANCELLED = "cancelled", _("Abgebrochen")


class Priority(models.TextChoices):
    LOW = "low", _("Niedrig")
    MEDIUM = "medium", _("Mittel")
    HIGH = "high", _("Hoch")
    URGENT = "urgent", _("Dringend")


class BillingModel(models.TextChoices):
    HOURLY = "hourly", _("Nach Aufwand")
    FIXED = "fixed", _("Festpreis")
    RETAINER = "retainer", _("Retainer")
    NON_BILLABLE = "non_billable", _("Nicht abrechenbar")


class Project(WorkspaceScopedModel, BaseModel):
    client = models.ForeignKey("crm.Client", on_delete=models.PROTECT, related_name="projects")
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=ProjectStatus.choices, default=ProjectStatus.ACTIVE, db_index=True
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    lead = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_projects",
    )
    team = models.ManyToManyField("accounts.User", blank=True, related_name="projects")
    default_hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leer ⇒ Kundensatz bzw. Workspace-Standard."),
    )
    budget_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    budget_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    billing_model = models.CharField(
        max_length=20, choices=BillingModel.choices, default=BillingModel.HOURLY
    )
    progress = models.PositiveSmallIntegerField(default=0, help_text=_("0–100 %"))
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    color = models.CharField(max_length=7, blank=True, help_text=_("Hex, z. B. #4f7dff"))
    archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["workspace", "status", "archived"])]

    def __str__(self) -> str:
        return self.name


class PhaseStatus(models.TextChoices):
    PLANNED = "planned", _("Geplant")
    ACTIVE = "active", _("Aktiv")
    COMPLETED = "completed", _("Abgeschlossen")


class ProjectPhase(WorkspaceScopedModel, BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="phases")
    name = models.CharField(max_length=200)
    order = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=PhaseStatus.choices, default=PhaseStatus.PLANNED
    )
    planned_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["project", "order"]

    def __str__(self) -> str:
        return f"{self.project.name} · {self.name}"


class BoardType(models.TextChoices):
    KANBAN = "kanban", _("Kanban")
    SCRUM = "scrum", _("Scrum")


class BoardViewType(models.TextChoices):
    KANBAN = "kanban", _("Kanban")
    TABLE = "table", _("Tabelle")


class Board(WorkspaceScopedModel, BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="boards")
    name = models.CharField(max_length=200)
    board_type = models.CharField(
        max_length=10, choices=BoardType.choices, default=BoardType.KANBAN
    )
    default_view = models.CharField(
        max_length=10, choices=BoardViewType.choices, default=BoardViewType.KANBAN
    )

    class Meta:
        ordering = ["project__name", "name"]

    def __str__(self) -> str:
        return f"{self.project.name} · {self.name}"


class SprintStatus(models.TextChoices):
    PLANNED = "planned", _("Geplant")
    ACTIVE = "active", _("Aktiv")
    COMPLETED = "completed", _("Abgeschlossen")


class Sprint(WorkspaceScopedModel, BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="sprints")
    board = models.ForeignKey(
        Board, on_delete=models.SET_NULL, null=True, blank=True, related_name="sprints"
    )
    name = models.CharField(max_length=100)
    goal = models.CharField(max_length=300, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=SprintStatus.choices, default=SprintStatus.PLANNED, db_index=True
    )
    capacity_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-start_date", "name"]

    def __str__(self) -> str:
        return f"{self.project.name} · {self.name}"


class TaskStatus(models.TextChoices):
    """Fixed status set = the kanban columns. Custom statuses are a later phase."""

    TODO = "todo", _("Zu erledigen")
    IN_PROGRESS = "in_progress", _("In Arbeit")
    REVIEW = "review", _("Review")
    DONE = "done", _("Erledigt")
    STUCK = "stuck", _("Blockiert")


class Task(WorkspaceScopedModel, BaseModel):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="tasks")
    phase = models.ForeignKey(
        ProjectPhase, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    board = models.ForeignKey(Board, on_delete=models.CASCADE, related_name="tasks")
    sprint = models.ForeignKey(
        Sprint, on_delete=models.SET_NULL, null=True, blank=True, related_name="tasks"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="subtasks"
    )
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=TaskStatus.choices, default=TaskStatus.TODO, db_index=True
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assignees = models.ManyToManyField("accounts.User", blank=True, related_name="tasks")
    created_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="created_tasks"
    )
    start_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True, db_index=True)
    estimated_hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    billable = models.BooleanField(default=True)
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    # Fractional rank: dropping a card between two others assigns the midpoint —
    # one UPDATE. Integer positions would renumber the whole column per drag and
    # race under concurrent moves.
    order = models.DecimalField(max_digits=20, decimal_places=10, default=ORDER_STEP)
    story_points = models.PositiveSmallIntegerField(null=True, blank=True)
    progress = models.PositiveSmallIntegerField(default=0)
    archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["status", "order", "created_at"]
        indexes = [
            models.Index(fields=["board", "status", "order"]),
            models.Index(fields=["workspace", "due_date"]),
        ]

    def __str__(self) -> str:
        return self.title


class TaskComment(WorkspaceScopedModel, BaseModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="task_comments"
    )
    content = models.TextField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        return f"Kommentar zu {self.task_id}"


class TaskChecklistItem(WorkspaceScopedModel, BaseModel):
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="checklist")
    title = models.CharField(max_length=300)
    done = models.BooleanField(default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self) -> str:
        return self.title
