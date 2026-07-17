"""Demo service types and ~4 weeks of time entries. Idempotent."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from apps.core.seeding import SeedContext, register_seeder
from apps.projects.models import Project, Task
from apps.timetracking.models import BillingStatus, EntrySource, ServiceType, TimeEntry
from apps.timetracking.services import compute_amount, resolve_hourly_rate

BERLIN = ZoneInfo("Europe/Berlin")

SERVICE_TYPES = [
    ("Entwicklung", "Implementierung und Bugfixing", Decimal("95.00")),
    ("Beratung", "Konzeption, Architektur, Workshops", Decimal("110.00")),
    ("Projektmanagement", "Koordination und Abstimmung", Decimal("90.00")),
    ("Support", "Wartung und Störungsbehebung", Decimal("85.00")),
]

# Weight of each project in the generated history (sums to 1).
PROJECT_WEIGHTS = [
    ("Website Relaunch", 0.4),
    ("Mobile App MVP", 0.3),
    ("Online-Buchungssystem", 0.2),
    ("Wartung & Support", 0.1),
]

DESCRIPTIONS = {
    "Website Relaunch": [
        "Produktdetailseite: Galerie-Komponente",
        "Design-System: Button- und Formularvarianten",
        "Review Navigationskonzept mit Frau Schneider",
        "Checkout: Datenmodell Bestellungen",
    ],
    "Mobile App MVP": [
        "Offline-Sync: Queue-Implementierung",
        "Login-Flow: Token-Refresh",
        "Abstimmung mit Herrn Krause (Sprint-Review)",
        "Kartenansicht: Prototyp",
    ],
    "Online-Buchungssystem": [
        "Verfügbarkeitskalender: Saisonpreise",
        "Anforderungsworkshop nachbereiten",
        "Channel-Manager: API-Dokumentation sichten",
    ],
    "Wartung & Support": [
        "Pipeline-Fehler analysiert und behoben",
        "Monitoring-Alerts konsolidiert",
        "Dependency-Updates eingespielt",
    ],
}


@register_seeder("timetracking", order=30)
def seed_timetracking(ctx: SeedContext) -> str:
    service_types: dict[str, ServiceType] = {}
    for name, description, rate in SERVICE_TYPES:
        st, _ = ServiceType.objects.get_or_create(
            workspace=ctx.workspace,
            name=name,
            defaults={"description": description, "default_hourly_rate": rate},
        )
        service_types[name] = st

    # Idempotency: the generated history is deterministic (seeded RNG), so a
    # re-run would recreate identical rows. Guard on "already seeded" instead of
    # per-row natural keys, which durations don't have.
    already = TimeEntry.objects.filter(
        workspace=ctx.workspace, source=EntrySource.MANUAL, description__startswith="[Demo] "
    ).count()
    if already:
        total = TimeEntry.objects.filter(workspace=ctx.workspace).count()
        return f"{total} Zeiteinträge (bereits vorhanden, übersprungen)"

    rng = random.Random(ctx.seed)  # noqa: S311 - demo data, not crypto
    projects = {
        p.name: p for p in Project.objects.filter(workspace=ctx.workspace).select_related("client")
    }
    tasks_by_project: dict[str, list[Task]] = {}
    for task in Task.objects.filter(workspace=ctx.workspace).select_related("project"):
        tasks_by_project.setdefault(task.project.name, []).append(task)

    created = 0
    today = datetime.now(tz=BERLIN).date()
    for day_offset in range(28, -1, -1):
        day = today - timedelta(days=day_offset)
        if day.weekday() >= 5:  # weekends stay free
            continue
        # 2–4 entries per workday
        cursor = datetime(day.year, day.month, day.day, 8, 30, tzinfo=BERLIN)
        for _ in range(rng.randint(2, 4)):
            name = rng.choices(
                [n for n, _ in PROJECT_WEIGHTS], weights=[w for _, w in PROJECT_WEIGHTS]
            )[0]
            project = projects.get(name)
            if project is None:
                continue
            duration_minutes = rng.choice([30, 45, 60, 90, 120, 150, 180, 240])
            started = cursor + timedelta(minutes=rng.randint(0, 20))
            ended = started + timedelta(minutes=duration_minutes)
            cursor = ended + timedelta(minutes=rng.randint(10, 45))
            if ended.hour >= 19:
                break

            service = service_types[
                "Support"
                if name == "Wartung & Support"
                else rng.choice(
                    ["Entwicklung", "Entwicklung", "Entwicklung", "Beratung", "Projektmanagement"]
                )
            ]
            candidates: list[Task | None] = list(tasks_by_project.get(name, [])) or [None]
            task = rng.choice(candidates)
            billable = name != "Wartung & Support" or rng.random() > 0.2
            rate = resolve_hourly_rate(
                workspace=ctx.workspace,
                client=project.client,
                project=project,
                service_type=service,
            )
            seconds = duration_minutes * 60
            # Older billable entries are partly billed already, so the client
            # dashboard shows a realistic mix of open vs billed hours.
            if billable and day_offset > 18:
                billing = BillingStatus.BILLED
            elif billable:
                billing = BillingStatus.OPEN
            else:
                billing = BillingStatus.NOT_BILLABLE

            TimeEntry.objects.create(
                workspace=ctx.workspace,
                user=ctx.user,
                client=project.client,
                project=project,
                task=task,
                service_type=service,
                description=f"[Demo] {rng.choice(DESCRIPTIONS[name])}",
                started_at=started,
                ended_at=ended,
                duration_seconds=seconds,
                source=EntrySource.MANUAL,
                billable=billable,
                hourly_rate=rate,
                computed_amount=compute_amount(
                    duration_seconds=seconds, hourly_rate=rate, billable=billable
                ),
                billing_status=billing,
            )
            created += 1

    ctx.record("time_entries", created)
    return f"{created} Zeiteinträge über 4 Wochen"
