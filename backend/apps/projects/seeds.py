"""Demo projects, phases, boards, sprints and tasks. Idempotent by natural key."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from apps.core.seeding import SeedContext, register_seeder
from apps.crm.models import Client
from apps.projects.models import (
    ORDER_STEP,
    Board,
    BoardType,
    Priority,
    Project,
    ProjectPhase,
    ProjectStatus,
    Sprint,
    SprintStatus,
    Task,
    TaskChecklistItem,
    TaskComment,
    TaskStatus,
)

TODAY = date(2026, 7, 17)  # deterministic; near the seed's authoring date

PROJECTS: list[dict[str, Any]] = [
    {
        "client": "Musterfirma GmbH",
        "name": "Website Relaunch",
        "description": "Kompletter Relaunch des Webauftritts inkl. Shop-Anbindung.",
        "status": ProjectStatus.ACTIVE,
        "priority": Priority.HIGH,
        "color": "#4f7dff",
        "billing": "hourly",
        "budget_hours": Decimal("240"),
        "start": TODAY - timedelta(days=60),
        "target": TODAY + timedelta(days=45),
        "phases": ["Konzept", "Umsetzung", "Golive"],
        "board_type": BoardType.SCRUM,
    },
    {
        "client": "TechVision AG",
        "name": "Mobile App MVP",
        "description": "React-Native-App für Außendienst, Phase 1.",
        "status": ProjectStatus.ACTIVE,
        "priority": Priority.URGENT,
        "color": "#a855f7",
        "billing": "fixed",
        "budget_amount": Decimal("28000.00"),
        "start": TODAY - timedelta(days=30),
        "target": TODAY + timedelta(days=60),
        "phases": ["Design", "Entwicklung", "Testphase"],
        "board_type": BoardType.SCRUM,
    },
    {
        "client": "Hotel Bergblick GmbH & Co. KG",
        "name": "Online-Buchungssystem",
        "description": "Buchungsstrecke mit Channel-Manager-Anbindung.",
        "status": ProjectStatus.ACTIVE,
        "priority": Priority.MEDIUM,
        "color": "#22c55e",
        "billing": "hourly",
        "budget_hours": Decimal("120"),
        "start": TODAY - timedelta(days=20),
        "target": TODAY + timedelta(days=30),
        "phases": ["Anforderungen", "Umsetzung"],
        "board_type": BoardType.KANBAN,
    },
    {
        "client": "DataWorks UG",
        "name": "Wartung & Support",
        "description": "Laufender Retainer: Pipeline-Betrieb und kleinere Features.",
        "status": ProjectStatus.ACTIVE,
        "priority": Priority.LOW,
        "color": "#f5a524",
        "billing": "retainer",
        "budget_hours": Decimal("20"),
        "start": TODAY - timedelta(days=180),
        "target": None,
        "phases": [],
        "board_type": BoardType.KANBAN,
    },
]

# (project, title, status, priority, points, due offset days, sprint?, phase index, checklist)
TASKS: list[tuple[str, str, str, str, int | None, int | None, bool, int | None, list[str]]] = [
    (
        "Website Relaunch",
        "Navigationskonzept finalisieren",
        TaskStatus.DONE,
        Priority.MEDIUM,
        3,
        -12,
        True,
        0,
        [],
    ),
    (
        "Website Relaunch",
        "Design-System Komponenten",
        TaskStatus.DONE,
        Priority.HIGH,
        5,
        -5,
        True,
        1,
        [],
    ),
    (
        "Website Relaunch",
        "Produktdetailseite umsetzen",
        TaskStatus.IN_PROGRESS,
        Priority.HIGH,
        8,
        4,
        True,
        1,
        ["Galerie-Komponente", "Varianten-Auswahl", "Warenkorb-Anbindung"],
    ),
    (
        "Website Relaunch",
        "Checkout-Strecke",
        TaskStatus.TODO,
        Priority.URGENT,
        13,
        9,
        True,
        1,
        ["Adressformular", "Zahlartenauswahl", "Bestellbestätigung"],
    ),
    (
        "Website Relaunch",
        "SEO-Weiterleitungen prüfen",
        TaskStatus.TODO,
        Priority.MEDIUM,
        2,
        14,
        False,
        2,
        [],
    ),
    (
        "Website Relaunch",
        "Ladezeit Startseite optimieren",
        TaskStatus.REVIEW,
        Priority.MEDIUM,
        3,
        2,
        True,
        1,
        [],
    ),
    (
        "Website Relaunch",
        "Kontaktformular Spam-Schutz",
        TaskStatus.STUCK,
        Priority.LOW,
        1,
        6,
        False,
        1,
        [],
    ),
    (
        "Mobile App MVP",
        "Login & Onboarding-Flow",
        TaskStatus.DONE,
        Priority.HIGH,
        5,
        -8,
        True,
        1,
        [],
    ),
    (
        "Mobile App MVP",
        "Offline-Synchronisation",
        TaskStatus.IN_PROGRESS,
        Priority.URGENT,
        13,
        5,
        True,
        1,
        ["Konfliktstrategie definieren", "Queue-Implementierung", "Sync-Tests"],
    ),
    (
        "Mobile App MVP",
        "Push-Benachrichtigungen",
        TaskStatus.TODO,
        Priority.MEDIUM,
        5,
        12,
        True,
        1,
        [],
    ),
    (
        "Mobile App MVP",
        "Kartenansicht Einsatzorte",
        TaskStatus.TODO,
        Priority.MEDIUM,
        8,
        16,
        False,
        1,
        [],
    ),
    (
        "Mobile App MVP",
        "App-Icon & Splashscreen",
        TaskStatus.REVIEW,
        Priority.LOW,
        1,
        1,
        True,
        0,
        [],
    ),
    (
        "Online-Buchungssystem",
        "Verfügbarkeitskalender",
        TaskStatus.IN_PROGRESS,
        Priority.HIGH,
        None,
        3,
        False,
        1,
        ["Saisonpreise", "Mindestaufenthalt"],
    ),
    (
        "Online-Buchungssystem",
        "Channel-Manager-API anbinden",
        TaskStatus.TODO,
        Priority.HIGH,
        None,
        10,
        False,
        1,
        [],
    ),
    (
        "Online-Buchungssystem",
        "Buchungsbestätigung per E-Mail",
        TaskStatus.TODO,
        Priority.MEDIUM,
        None,
        15,
        False,
        1,
        [],
    ),
    (
        "Online-Buchungssystem",
        "Anforderungsworkshop protokollieren",
        TaskStatus.DONE,
        Priority.MEDIUM,
        None,
        -15,
        False,
        0,
        [],
    ),
    (
        "Wartung & Support",
        "Monitoring-Alerts aufräumen",
        TaskStatus.DONE,
        Priority.LOW,
        None,
        -3,
        False,
        None,
        [],
    ),
    (
        "Wartung & Support",
        "Pipeline-Fehler vom Dienstag analysieren",
        TaskStatus.IN_PROGRESS,
        Priority.HIGH,
        None,
        1,
        False,
        None,
        [],
    ),
    (
        "Wartung & Support",
        "Postgres-Upgrade vorbereiten",
        TaskStatus.TODO,
        Priority.MEDIUM,
        None,
        21,
        False,
        None,
        ["Changelog sichten", "Staging-Test", "Wartungsfenster abstimmen"],
    ),
]


@register_seeder("projects", order=20)
def seed_projects(ctx: SeedContext) -> str:
    created_projects = 0
    boards: dict[str, Board] = {}
    sprints: dict[str, Sprint] = {}
    phases: dict[tuple[str, int], ProjectPhase] = {}

    for data in PROJECTS:
        client = Client.objects.get(workspace=ctx.workspace, name=data["client"])
        project, was_created = Project.objects.get_or_create(
            workspace=ctx.workspace,
            client=client,
            name=data["name"],
            defaults={
                "description": data["description"],
                "status": data["status"],
                "priority": data["priority"],
                "start_date": data["start"],
                "target_date": data["target"],
                "lead": ctx.user,
                "budget_hours": data.get("budget_hours"),
                "budget_amount": data.get("budget_amount"),
                "billing_model": data["billing"],
                "color": data["color"],
            },
        )
        created_projects += int(was_created)
        if was_created:
            project.team.add(ctx.user)

        board, _ = Board.objects.get_or_create(
            workspace=ctx.workspace,
            project=project,
            name="Hauptboard",
            defaults={"board_type": data["board_type"]},
        )
        boards[data["name"]] = board

        for order, phase_name in enumerate(data["phases"]):
            phase, _ = ProjectPhase.objects.get_or_create(
                workspace=ctx.workspace,
                project=project,
                name=phase_name,
                defaults={"order": order, "status": "active" if order <= 1 else "planned"},
            )
            phases[(data["name"], order)] = phase

        if data["board_type"] == BoardType.SCRUM:
            sprint, _ = Sprint.objects.get_or_create(
                workspace=ctx.workspace,
                project=project,
                name="Sprint 3" if data["name"] == "Website Relaunch" else "Sprint 1",
                defaults={
                    "board": board,
                    "goal": "Auslieferbarer Stand der Kernstrecke",
                    "start_date": TODAY - timedelta(days=7),
                    "end_date": TODAY + timedelta(days=7),
                    "status": SprintStatus.ACTIVE,
                    "capacity_hours": Decimal("30"),
                },
            )
            sprints[data["name"]] = sprint

    created_tasks = 0
    per_status_counter: dict[tuple[str, str], int] = {}
    for (
        project_name,
        title,
        status_,
        priority,
        points,
        due_offset,
        in_sprint,
        phase_idx,
        checklist,
    ) in TASKS:
        project = Project.objects.get(workspace=ctx.workspace, name=project_name)
        board = boards[project_name]
        key = (project_name, status_)
        per_status_counter[key] = per_status_counter.get(key, 0) + 1

        task, was_created = Task.objects.get_or_create(
            workspace=ctx.workspace,
            project=project,
            title=title,
            defaults={
                "board": board,
                "sprint": sprints.get(project_name) if in_sprint else None,
                "phase": phases.get((project_name, phase_idx)) if phase_idx is not None else None,
                "status": status_,
                "priority": priority,
                "story_points": points,
                "due_date": TODAY + timedelta(days=due_offset) if due_offset is not None else None,
                "billable": project_name != "Wartung & Support" or True,
                "created_by": ctx.user,
                "order": ORDER_STEP * per_status_counter[key],
                "estimated_hours": Decimal(points * 2) if points else None,
                "progress": 100
                if status_ == TaskStatus.DONE
                else (60 if status_ == TaskStatus.IN_PROGRESS else 0),
            },
        )
        created_tasks += int(was_created)
        if was_created:
            task.assignees.add(ctx.user)
            for order, item in enumerate(checklist):
                TaskChecklistItem.objects.create(
                    workspace=ctx.workspace,
                    task=task,
                    title=item,
                    order=order,
                    done=order == 0 and status_ != TaskStatus.TODO,
                )
            if status_ == TaskStatus.STUCK:
                TaskComment.objects.create(
                    workspace=ctx.workspace,
                    task=task,
                    author=ctx.user,
                    content="Warte auf Freigabe des Captcha-Anbieters durch den Kunden.",
                )
            if title == "Offline-Synchronisation":
                TaskComment.objects.create(
                    workspace=ctx.workspace,
                    task=task,
                    author=ctx.user,
                    content="Konfliktstrategie: Last-Write-Wins pro Feld, Protokoll im Wiki.",
                )

    ctx.record("projects", created_projects)
    ctx.record("tasks", created_tasks)
    total_p = Project.objects.filter(workspace=ctx.workspace).count()
    total_t = Task.objects.filter(workspace=ctx.workspace).count()
    return f"{total_p} Projekte ({created_projects} neu), {total_t} Aufgaben ({created_tasks} neu)"
