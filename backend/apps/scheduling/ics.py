"""ICS (iCalendar) export and import for appointments.

Uses the `icalendar` library. Import is idempotent on the event UID so
re-importing the same file updates rather than duplicates.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone
from icalendar import Calendar, Event

from apps.scheduling.models import Appointment


def appointments_to_ics(appointments: list[Appointment]) -> bytes:
    cal = Calendar()
    cal.add("prodid", "-//Coreflow//Termine//DE")
    cal.add("version", "2.0")
    for appointment in appointments:
        event = Event()
        event.add("uid", appointment.ics_uid)
        event.add("summary", appointment.title)
        if appointment.description:
            event.add("description", appointment.description)
        event.add("dtstart", appointment.starts_at)
        event.add("dtend", appointment.ends_at)
        event.add("dtstamp", appointment.created_at)
        if appointment.location:
            event.add("location", appointment.location)
        if appointment.video_link:
            event.add("url", appointment.video_link)
        cal.add_component(event)
    return cal.to_ical()


def parse_ics(raw: str | bytes) -> list[dict[str, Any]]:
    """Parse ICS text into event dicts. Skips events without a start/end."""
    cal = Calendar.from_ical(raw)
    events: list[dict[str, Any]] = []
    for component in cal.walk("VEVENT"):
        dtstart = component.get("dtstart")
        dtend = component.get("dtend")
        if dtstart is None or dtend is None:
            continue
        starts = _to_aware(dtstart.dt)
        ends = _to_aware(dtend.dt)
        events.append(
            {
                "uid": str(component.get("uid") or "") or f"import-{starts.isoformat()}@coreflow",
                "title": str(component.get("summary") or "Termin"),
                "description": str(component.get("description") or ""),
                "location": str(component.get("location") or ""),
                "starts_at": starts,
                "ends_at": ends,
            }
        )
    return events


def _to_aware(value: Any) -> datetime:
    """Normalise a date/datetime from ICS to an aware datetime (UTC storage)."""
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value
    # A date-only value (all-day event): treat as midnight local.
    return timezone.make_aware(
        datetime(value.year, value.month, value.day), timezone.get_current_timezone()
    )
