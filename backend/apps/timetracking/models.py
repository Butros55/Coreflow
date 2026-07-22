"""Internal time tracking — fully functional with Clockify disabled, forever."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


class ServiceType(WorkspaceScopedModel, BaseModel):
    """Leistungsart. Maps to a Clockify tag when that integration is on."""

    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    default_hourly_rate = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    default_invoice_text = models.CharField(max_length=300, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "name"], name="unique_service_type_name_per_workspace"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class BillingStatus(models.TextChoices):
    NOT_BILLABLE = "not_billable", _("Nicht abrechenbar")
    OPEN = "open", _("Offen")
    MARKED = "marked_for_invoice", _("Zur Rechnung vorgemerkt")
    DRAFT_CREATED = "invoice_draft_created", _("Rechnungsentwurf erstellt")
    BILLED = "billed", _("Abgerechnet")
    CANCELLED = "cancelled", _("Storniert")


class EntrySource(models.TextChoices):
    MANUAL = "manual", _("Manuell")
    TIMER = "timer", _("Timer")
    CLOCKIFY = "clockify", _("Clockify")
    # Reconstructed from an imported Lexware invoice line — the hours were
    # billed there before Coreflow existed and had no local counterpart. An
    # entry keeps this source even after it is linked to its Clockify twin;
    # the Clockify membership is visible via the ExternalObjectLink.
    LEXWARE = "lexware", _("Lexware")


class TimeEntry(WorkspaceScopedModel, BaseModel):
    user = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="time_entries")
    client = models.ForeignKey("crm.Client", on_delete=models.PROTECT, related_name="time_entries")
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    phase = models.ForeignKey(
        "projects.ProjectPhase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    task = models.ForeignKey(
        "projects.Task",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    service_type = models.ForeignKey(
        ServiceType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )
    description = models.CharField(max_length=500, blank=True)

    started_at = models.DateTimeField(db_index=True)
    # NULL ⇒ the timer is running. The partial unique constraint below is the
    # real "one running timer per user" guarantee — an application-level check
    # loses the race between two tabs.
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)

    source = models.CharField(
        max_length=10, choices=EntrySource.choices, default=EntrySource.MANUAL
    )
    billable = models.BooleanField(default=True)
    # Snapshotted at creation: raising a client's rate must not retroactively
    # change what last quarter's unbilled work is worth.
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2)
    computed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    billing_status = models.CharField(
        max_length=25, choices=BillingStatus.choices, default=BillingStatus.OPEN, db_index=True
    )
    # Pre-rounding duration, kept for the audit trail. NULL = no rounding applied.
    rounded_from_seconds = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name_plural = "time entries"
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(ended_at__isnull=True),
                name="one_running_timer_per_user",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(ended_at__isnull=True) | models.Q(ended_at__gt=models.F("started_at"))
                ),
                name="time_entry_ends_after_start",
            ),
        ]
        indexes = [
            models.Index(fields=["workspace", "started_at"]),
            models.Index(fields=["workspace", "billing_status"]),
            models.Index(fields=["client", "billing_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.client} · {self.duration_seconds}s"

    @property
    def is_running(self) -> bool:
        return self.ended_at is None
