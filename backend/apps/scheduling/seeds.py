"""Demo appointments across the coming weeks."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apps.core.seeding import SeedContext, register_seeder
from apps.crm.models import Client
from apps.projects.models import Project
from apps.scheduling.models import Appointment, AppointmentStatus

BERLIN = ZoneInfo("Europe/Berlin")

APPOINTMENTS = [
    (
        "Kickoff Website Relaunch",
        "Musterfirma GmbH",
        "Website Relaunch",
        -3,
        9,
        60,
        AppointmentStatus.DONE,
        "Scope bestätigt, Zugänge erhalten.",
        "Designentwürfe bis Freitag.",
    ),
    (
        "Sprint-Review Mobile App",
        "TechVision AG",
        "Mobile App MVP",
        1,
        14,
        45,
        AppointmentStatus.CONFIRMED,
        "",
        "",
    ),
    (
        "Anforderungsworkshop Buchung",
        "Hotel Bergblick GmbH & Co. KG",
        "Online-Buchungssystem",
        2,
        10,
        90,
        AppointmentStatus.PLANNED,
        "",
        "",
    ),
    (
        "Monatliches Retainer-Gespräch",
        "DataWorks UG",
        "Wartung & Support",
        5,
        11,
        30,
        AppointmentStatus.PLANNED,
        "",
        "",
    ),
    (
        "Erstgespräch Due-Diligence-Tool",
        "StartHub Ventures",
        None,
        7,
        16,
        60,
        AppointmentStatus.PLANNED,
        "",
        "",
    ),
]


@register_seeder("scheduling", order=60)
def seed_scheduling(ctx: SeedContext) -> str:
    if Appointment.objects.filter(workspace=ctx.workspace).exists():
        count = Appointment.objects.filter(workspace=ctx.workspace).count()
        return f"{count} Termine (bereits vorhanden, übersprungen)"

    today = datetime.now(tz=BERLIN).date()
    created = 0
    for (
        title,
        client_name,
        project_name,
        day_offset,
        hour,
        duration,
        status,
        outcome,
        steps,
    ) in APPOINTMENTS:
        client = Client.objects.filter(workspace=ctx.workspace, name=client_name).first()
        project = (
            Project.objects.filter(workspace=ctx.workspace, name=project_name).first()
            if project_name
            else None
        )
        start = datetime.combine(
            today + timedelta(days=day_offset),
            datetime.min.time().replace(hour=hour),
            tzinfo=BERLIN,
        )
        appointment = Appointment.objects.create(
            workspace=ctx.workspace,
            client=client,
            project=project,
            title=title,
            starts_at=start,
            ends_at=start + timedelta(minutes=duration),
            location="Videocall" if day_offset % 2 else "Vor Ort",
            video_link="https://meet.example.com/coreflow" if day_offset % 2 else "",
            status=status,
            outcome_notes=outcome,
            next_steps=steps,
        )
        appointment.participants.add(ctx.user)
        created += 1

    return f"{created} Termine"
