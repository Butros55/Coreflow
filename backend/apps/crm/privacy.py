"""GDPR tooling for clients: data export and erasure with legal hold.

Erasure follows Art. 17 DSGVO **within** the retention duties of § 147 AO and
§ 257 HGB: accounting records (invoices, the time entries they bill, and the
business metadata on both) must be kept for up to 10 years and are therefore
NOT deleted. What erasure does:

* purge the client's satellites (contacts, notes, activities, appointments'
  client link stays but appointments belong to the operator's calendar),
* blank every personal/contact field on the client record,
* replace the name with a neutral tombstone,
* keep invoices, projects and time entries intact under legal hold.

A client with **no** business records at all is deleted outright — there is
nothing the law requires us to keep.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.crm.models import Client, ClientStatus

LEGAL_HOLD_BASIS = "§ 147 AO / § 257 HGB (Aufbewahrungspflicht bis zu 10 Jahre)"

# Personal/contact fields blanked on erasure. Everything else on the client is
# either the tombstone name or business bookkeeping data under legal hold.
_ERASED_FIELDS = (
    "short_name",
    "legal_form",
    "industry",
    "website",
    "email",
    "phone",
    "billing_street",
    "billing_zip",
    "billing_city",
    "shipping_street",
    "shipping_zip",
    "shipping_city",
    "shipping_country_code",
    "tax_number",
    "vat_id",
    "notes",
    "acquisition_source",
)


def export_client_data(client: Client) -> dict[str, Any]:
    """Art. 15/20 DSGVO: everything stored about this client, as one bundle."""
    contacts = [
        {
            "first_name": c.first_name,
            "last_name": c.last_name,
            "email": c.email,
            "phone": c.phone,
            "mobile": c.mobile,
            "position": c.position,
            "is_primary": c.is_primary,
            "created_at": c.created_at.isoformat(),
        }
        for c in client.contacts.all()
    ]
    notes = [
        {
            "content": n.content,
            "note_type": n.note_type,
            "created_at": n.created_at.isoformat(),
        }
        for n in client.client_notes.all()
    ]
    activities = [
        {
            "event_type": a.event_type,
            "description": a.description,
            "occurred_at": a.occurred_at.isoformat(),
        }
        for a in client.activities.all()
    ]
    time_entries = [
        {
            "date": e.started_at.date().isoformat(),
            "duration_seconds": e.duration_seconds,
            "description": e.description,
            "amount": str(e.computed_amount),
            "billing_status": e.billing_status,
        }
        for e in client.time_entries.all().order_by("started_at")
    ]
    invoices = [
        {
            "invoice_number": i.invoice_number,
            "status": i.status,
            "net_amount": str(i.net_amount),
            "gross_amount": str(i.gross_amount),
            "period_start": i.period_start.isoformat() if i.period_start else None,
            "period_end": i.period_end.isoformat() if i.period_end else None,
            "created_at": i.created_at.isoformat(),
        }
        for i in client.invoices.all().order_by("created_at")
    ]
    projects = [
        {"name": p.name, "status": p.status, "created_at": p.created_at.isoformat()}
        for p in client.projects.all()
    ]
    appointments = [
        {"title": a.title, "starts_at": a.starts_at.isoformat()} for a in client.appointments.all()
    ]

    client_fields = {
        "name": client.name,
        "short_name": client.short_name,
        "client_number": client.client_number,
        "status": client.status,
        "email": client.email,
        "phone": client.phone,
        "website": client.website,
        "billing_address": {
            "street": client.billing_street,
            "zip": client.billing_zip,
            "city": client.billing_city,
            "country": client.billing_country_code,
        },
        "tax_number": client.tax_number,
        "vat_id": client.vat_id,
        "tags": list(client.tags),
        "customer_since": (client.customer_since.isoformat() if client.customer_since else None),
        "created_at": client.created_at.isoformat(),
    }
    return {
        "export_note": (
            "Datenauskunft nach Art. 15 DSGVO. Rechnungsdaten unterliegen der "
            f"Aufbewahrungspflicht: {LEGAL_HOLD_BASIS}."
        ),
        "client": client_fields,
        "contacts": contacts,
        "notes": notes,
        "activities": activities,
        "time_entries": time_entries,
        "invoices": invoices,
        "projects": projects,
        "appointments": appointments,
    }


def has_retention_records(client: Client) -> bool:
    """True when accounting law forbids a hard delete."""
    return client.invoices.exists() or client.time_entries.exists() or client.projects.exists()


@transaction.atomic
def erase_client(client: Client) -> dict[str, Any]:
    """Erase or anonymise, depending on legal hold. Returns what happened."""
    if not has_retention_records(client):
        client_id = str(client.pk)
        client.contacts.all().delete()
        client.client_notes.all().delete()
        client.activities.all().delete()
        client.delete()
        return {"mode": "deleted", "client_id": client_id, "retained": []}

    deleted_contacts = client.contacts.all().count()
    deleted_notes = client.client_notes.all().count()
    deleted_activities = client.activities.all().count()
    client.contacts.all().delete()
    client.client_notes.all().delete()
    client.activities.all().delete()

    for field in _ERASED_FIELDS:
        setattr(client, field, "")
    client.name = f"Gelöschter Kunde {str(client.pk)[:8]}"
    client.tags = []
    client.customer_since = None
    client.status = ClientStatus.FORMER
    client.archived = True
    client.save()

    return {
        "mode": "anonymized",
        "client_id": str(client.pk),
        "deleted": {
            "contacts": deleted_contacts,
            "notes": deleted_notes,
            "activities": deleted_activities,
        },
        "retained": ["invoices", "time_entries", "projects"],
        "legal_basis": LEGAL_HOLD_BASIS,
    }
