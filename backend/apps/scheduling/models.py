"""Appointments and calendar."""

from __future__ import annotations

import uuid

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


class AppointmentStatus(models.TextChoices):
    PLANNED = "planned", _("Geplant")
    CONFIRMED = "confirmed", _("Bestätigt")
    DONE = "done", _("Erledigt")
    CANCELLED = "cancelled", _("Abgesagt")


class Appointment(WorkspaceScopedModel, BaseModel):
    client = models.ForeignKey(
        "crm.Client", on_delete=models.SET_NULL, null=True, blank=True, related_name="appointments"
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=255, blank=True)
    video_link = models.URLField(blank=True)
    participants = models.ManyToManyField("accounts.User", blank=True, related_name="appointments")
    status = models.CharField(
        max_length=20, choices=AppointmentStatus.choices, default=AppointmentStatus.PLANNED
    )
    reminder_minutes_before = models.PositiveIntegerField(null=True, blank=True)
    outcome_notes = models.TextField(blank=True)
    next_steps = models.TextField(blank=True)
    # Stable across ICS export/import round-trips so re-importing does not
    # duplicate an appointment.
    ics_uid = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        ordering = ["starts_at"]
        indexes = [models.Index(fields=["workspace", "starts_at"])]

    def __str__(self) -> str:
        return self.title

    def save(self, *args: object, **kwargs: object) -> None:
        if not self.ics_uid:
            self.ics_uid = f"{self.pk or uuid.uuid4()}@coreflow"
        super().save(*args, **kwargs)  # type: ignore[arg-type]
