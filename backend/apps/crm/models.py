"""CRM: clients, contacts, notes, and the per-client activity feed."""

from __future__ import annotations

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


class ClientStatus(models.TextChoices):
    PROSPECT = "prospect", _("Interessent")
    ACTIVE = "active", _("Aktiv")
    PAUSED = "paused", _("Pausiert")
    FORMER = "former", _("Ehemalig")


class Client(WorkspaceScopedModel, BaseModel):
    """A customer. Lexware/Clockify mapping lives in ExternalObjectLink, not here."""

    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=50, blank=True)
    legal_form = models.CharField(max_length=100, blank=True)
    client_number = models.CharField(
        max_length=20,
        blank=True,
        help_text=_("Auto-vergeben (K-1001, …) wenn leer."),
    )
    status = models.CharField(
        max_length=20, choices=ClientStatus.choices, default=ClientStatus.ACTIVE, db_index=True
    )
    industry = models.CharField(max_length=120, blank=True)
    website = models.URLField(blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)

    billing_street = models.CharField(max_length=255, blank=True)
    billing_zip = models.CharField(max_length=20, blank=True)
    billing_city = models.CharField(max_length=120, blank=True)
    billing_country_code = models.CharField(max_length=2, default="DE")

    shipping_street = models.CharField(max_length=255, blank=True)
    shipping_zip = models.CharField(max_length=20, blank=True)
    shipping_city = models.CharField(max_length=120, blank=True)
    shipping_country_code = models.CharField(max_length=2, blank=True)

    tax_number = models.CharField(max_length=50, blank=True)
    vat_id = models.CharField(max_length=50, blank=True)

    default_hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leer ⇒ Workspace-Standard."),
    )
    payment_term_days = models.PositiveSmallIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="EUR")

    notes = models.TextField(blank=True)
    tags = ArrayField(models.CharField(max_length=40), default=list, blank=True)
    acquisition_source = models.CharField(max_length=120, blank=True)
    customer_since = models.DateField(null=True, blank=True)
    archived = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "client_number"],
                condition=~models.Q(client_number=""),
                name="unique_client_number_per_workspace",
            ),
        ]
        indexes = [models.Index(fields=["workspace", "status", "archived"])]

    def __str__(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return self.short_name or self.name


class PreferredChannel(models.TextChoices):
    EMAIL = "email", _("E-Mail")
    PHONE = "phone", _("Telefon")
    MOBILE = "mobile", _("Mobil")
    OTHER = "other", _("Sonstiges")


class ClientContact(WorkspaceScopedModel, BaseModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="contacts")
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    position = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    mobile = models.CharField(max_length=50, blank=True)
    preferred_channel = models.CharField(
        max_length=10, choices=PreferredChannel.choices, default=PreferredChannel.EMAIL
    )
    is_primary = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-is_primary", "last_name", "first_name"]
        constraints = [
            # One primary contact per client, enforced in the database — two
            # concurrent "make primary" requests would otherwise both win.
            models.UniqueConstraint(
                fields=["client"],
                condition=models.Q(is_primary=True),
                name="unique_primary_contact_per_client",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class NoteType(models.TextChoices):
    NOTE = "note", _("Notiz")
    CALL = "call", _("Telefonat")
    MEETING = "meeting", _("Termin")
    EMAIL = "email", _("E-Mail")


class ClientNote(WorkspaceScopedModel, BaseModel):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_notes")
    author = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, related_name="client_notes"
    )
    content = models.TextField()
    note_type = models.CharField(max_length=10, choices=NoteType.choices, default=NoteType.NOTE)
    follow_up_at = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_note_type_display()} zu {self.client}"


class ActivityType(models.TextChoices):
    CLIENT_CREATED = "client_created", _("Kunde angelegt")
    CONTACT_ADDED = "contact_added", _("Ansprechpartner hinzugefügt")
    NOTE_ADDED = "note_added", _("Notiz erstellt")
    PROJECT_CREATED = "project_created", _("Projekt angelegt")
    TASK_COMPLETED = "task_completed", _("Aufgabe abgeschlossen")
    TIME_TRACKED = "time_tracked", _("Zeit erfasst")
    STATUS_CHANGED = "status_changed", _("Status geändert")


class ClientActivity(WorkspaceScopedModel, BaseModel):
    """Append-only feed. Invoice/appointment references arrive with their phases."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="activities")
    event_type = models.CharField(max_length=30, choices=ActivityType.choices, db_index=True)
    description = models.CharField(max_length=500)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    note = models.ForeignKey(
        ClientNote, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-occurred_at"]
        verbose_name_plural = "client activities"

    def __str__(self) -> str:
        return f"{self.event_type}: {self.description[:60]}"


def next_client_number(workspace_id: uuid.UUID | str) -> str:
    """K-1001, K-1002, … per workspace. Race-tolerant enough for a 1-person org;
    the DB constraint is the final arbiter."""
    prefix = "K-"
    existing = Client.objects.filter(
        workspace_id=workspace_id, client_number__startswith=prefix
    ).values_list("client_number", flat=True)
    highest = 1000
    for number in existing:
        try:
            highest = max(highest, int(number.removeprefix(prefix)))
        except ValueError:
            continue
    return f"{prefix}{highest + 1}"
