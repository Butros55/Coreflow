"""Demo clients, contacts, notes and activity history. Idempotent by name."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from django.utils import timezone

from apps.core.seeding import SeedContext, register_seeder
from apps.crm.models import (
    ActivityType,
    Client,
    ClientActivity,
    ClientContact,
    ClientNote,
    ClientStatus,
    NoteType,
)

CLIENTS: list[dict[str, Any]] = [
    {
        "name": "Musterfirma GmbH",
        "short_name": "Musterfirma",
        "legal_form": "GmbH",
        "number": "K-1001",
        "status": ClientStatus.ACTIVE,
        "industry": "Maschinenbau",
        "city": "Freiburg",
        "zip": "79098",
        "street": "Industriestraße 12",
        "rate": "95.00",
        "tags": ["Stammkunde", "Wartungsvertrag"],
        "source": "Empfehlung",
        "since": date(2022, 3, 1),
        "contacts": [
            ("Petra", "Schneider", "Geschäftsführung", "p.schneider@musterfirma.de", True),
            ("Jonas", "Weber", "IT-Leitung", "j.weber@musterfirma.de", False),
        ],
    },
    {
        "name": "TechVision AG",
        "short_name": "TechVision",
        "legal_form": "AG",
        "number": "K-1002",
        "status": ClientStatus.ACTIVE,
        "industry": "Software",
        "city": "Karlsruhe",
        "zip": "76133",
        "street": "Kaiserstraße 88",
        "rate": "110.00",
        "tags": ["Festpreis"],
        "source": "LinkedIn",
        "since": date(2023, 6, 15),
        "contacts": [("Daniel", "Krause", "CTO", "krause@techvision.ag", True)],
    },
    {
        "name": "Hotel Bergblick GmbH & Co. KG",
        "short_name": "Bergblick",
        "legal_form": "GmbH & Co. KG",
        "number": "K-1003",
        "status": ClientStatus.ACTIVE,
        "industry": "Hotellerie",
        "city": "Titisee-Neustadt",
        "zip": "79822",
        "street": "Seestraße 3",
        "rate": "85.00",
        "tags": ["Saisonal"],
        "source": "Website",
        "since": date(2023, 11, 2),
        "contacts": [
            ("Maria", "Huber", "Inhaberin", "info@hotel-bergblick.de", True),
        ],
    },
    {
        "name": "DataWorks UG",
        "short_name": "DataWorks",
        "legal_form": "UG",
        "number": "K-1004",
        "status": ClientStatus.ACTIVE,
        "industry": "Datenanalyse",
        "city": "Basel",
        "zip": "4051",
        "street": "Steinenvorstadt 2",
        "rate": "105.00",
        "tags": ["Retainer", "Remote"],
        "source": "Konferenz",
        "since": date(2024, 1, 10),
        "contacts": [("Simon", "Frei", "Data Lead", "simon@dataworks.ch", True)],
    },
    {
        "name": "Nordlicht Media",
        "short_name": "Nordlicht",
        "legal_form": "Einzelunternehmen",
        "number": "K-1005",
        "status": ClientStatus.PAUSED,
        "industry": "Agentur",
        "city": "Hamburg",
        "zip": "20095",
        "street": "Mönckebergstraße 17",
        "rate": None,
        "tags": [],
        "source": "Empfehlung",
        "since": date(2023, 2, 20),
        "contacts": [("Lena", "Voss", "Projektleitung", "lena@nordlicht.media", True)],
    },
    {
        "name": "StartHub Ventures",
        "short_name": "StartHub",
        "legal_form": "GmbH",
        "number": "K-1006",
        "status": ClientStatus.PROSPECT,
        "industry": "Beteiligungen",
        "city": "Berlin",
        "zip": "10115",
        "street": "Torstraße 140",
        "rate": None,
        "tags": ["Akquise"],
        "source": "Kaltakquise",
        "since": None,
        "contacts": [("Felix", "Brandt", "Partner", "brandt@starthub.vc", True)],
    },
]

NOTES = [
    (
        "Musterfirma GmbH",
        NoteType.MEETING,
        "Quartalsplanung: Relaunch-Phase 2 ab August, Budget bestätigt. "
        "Wartungsfenster weiterhin dienstags.",
    ),
    (
        "Musterfirma GmbH",
        NoteType.CALL,
        "Herr Weber meldet sporadische Timeouts im Bestellmodul — Monitoring-Daten angefordert.",
    ),
    (
        "TechVision AG",
        NoteType.NOTE,
        "Angebot für App-Phase 2 versendet. Entscheidung laut Krause bis Ende des Monats.",
    ),
    (
        "Hotel Bergblick GmbH & Co. KG",
        NoteType.EMAIL,
        "Saisonstart: Buchungsmaske soll vor Pfingsten live gehen. Texte kommen von Frau Huber.",
    ),
    (
        "DataWorks UG",
        NoteType.MEETING,
        "Monatliches Retainer-Review: Pipeline stabil, nächster Fokus Datenqualitäts-Checks.",
    ),
    (
        "StartHub Ventures",
        NoteType.CALL,
        "Erstgespräch: suchen Entwickler für Due-Diligence-Tool, Folgetermin vereinbart.",
    ),
]


@register_seeder("crm", order=10)
def seed_crm(ctx: SeedContext) -> str:
    now = timezone.now()
    created_clients = 0

    for index, data in enumerate(CLIENTS):
        client, was_created = Client.objects.get_or_create(
            workspace=ctx.workspace,
            name=data["name"],
            defaults={
                "short_name": data["short_name"],
                "legal_form": data["legal_form"],
                "client_number": data["number"],
                "status": data["status"],
                "industry": data["industry"],
                "billing_street": data["street"],
                "billing_zip": data["zip"],
                "billing_city": data["city"],
                "billing_country_code": "CH" if data["city"] == "Basel" else "DE",
                "email": data["contacts"][0][3],
                "default_hourly_rate": data["rate"],
                "payment_term_days": 14,
                "currency": "EUR",
                "tags": data["tags"],
                "acquisition_source": data["source"],
                "customer_since": data["since"],
            },
        )
        created_clients += int(was_created)

        for first, last, position, email, primary in data["contacts"]:
            ClientContact.objects.get_or_create(
                workspace=ctx.workspace,
                client=client,
                first_name=first,
                last_name=last,
                defaults={
                    "position": position,
                    "email": email,
                    "phone": f"+49 761 55{index}0{len(first)}1",
                    "preferred_channel": "email",
                    "is_primary": primary,
                },
            )

        if was_created:
            ClientActivity.objects.create(
                workspace=ctx.workspace,
                client=client,
                event_type=ActivityType.CLIENT_CREATED,
                description=f"Kunde „{client.name}“ angelegt",
                occurred_at=now - timedelta(days=40 - index * 3),
                actor=ctx.user,
            )

    created_notes = 0
    for offset, (client_name, note_type, content) in enumerate(NOTES):
        client = Client.objects.get(workspace=ctx.workspace, name=client_name)
        note, was_created = ClientNote.objects.get_or_create(
            workspace=ctx.workspace,
            client=client,
            content=content,
            defaults={"author": ctx.user, "note_type": note_type},
        )
        created_notes += int(was_created)
        if was_created:
            # Spread the feed over the past weeks so it reads like history.
            occurred = now - timedelta(days=2 + offset * 4, hours=offset)
            ClientNote.objects.filter(pk=note.pk).update(created_at=occurred)
            ClientActivity.objects.create(
                workspace=ctx.workspace,
                client=client,
                event_type=ActivityType.NOTE_ADDED,
                description=f"{note.get_note_type_display()}: {content[:70]}",
                occurred_at=occurred,
                actor=ctx.user,
                note=note,
            )

    ctx.record("clients", created_clients)
    total = Client.objects.filter(workspace=ctx.workspace).count()
    return f"{total} Kunden ({created_clients} neu), {created_notes} Notizen neu"
