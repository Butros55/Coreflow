"""Local invoice mirror and the invoice-from-time-entries workflow.

Lexware is the system of record for finalised invoices; this app owns the
*composition* workflow (selecting time entries, grouping them, editing the
draft) and a local mirror of whatever Lexware returns.

The whole draft can be built and edited **before any network call** — an
``Invoice`` in ``draft_local`` never touched Lexware. That is what keeps the
workflow usable with ``LEXWARE_ENABLED=false``.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel


class InvoiceStatus(models.TextChoices):
    """See docs/integrations/lexware.md §6 for the full state machine.

    ``draft_local`` exists before any network call. ``send_pending`` covers the
    504 hazard (a Lexware timeout may mean the invoice *was* created — see the
    reconciliation path). Lexware assigns the number and finalises; we mirror.
    """

    DRAFT_LOCAL = "draft_local", _("Lokaler Entwurf")
    SEND_PENDING = "send_pending", _("Übertragung läuft")
    DRAFT_REMOTE = "draft_remote", _("Lexware-Entwurf")
    OPEN = "open", _("Offen")
    PAID = "paid", _("Bezahlt")
    OVERDUE = "overdue", _("Überfällig")
    VOIDED = "voided", _("Storniert")


# Statuses in which the invoice still holds its time entries but is not a live
# claim on them for double-billing purposes.
CANCELLED_STATUSES = frozenset({InvoiceStatus.VOIDED})


class TaxType(models.TextChoices):
    """Mirrors the documented Lexware invoice taxConditions.taxType subset we use.

    Defaulted from the connected profile, never hardcoded per invoice — see
    docs/integrations/lexware.md §4.5.
    """

    NET = "net", _("Netto (zzgl. USt)")
    GROSS = "gross", _("Brutto (inkl. USt)")
    VATFREE = "vatfree", _("Steuerfrei / Kleinunternehmer §19 UStG")


class InvoiceGrouping(models.TextChoices):
    PER_ENTRY = "per_entry", _("Einzelposition")
    PER_DAY = "per_day", _("Pro Tag")
    PER_SERVICE = "per_service", _("Pro Leistungsart")
    PER_PHASE = "per_phase", _("Pro Projektphase")
    PER_TASK = "per_task", _("Pro Aufgabe")
    LUMP_SUM = "lump_sum", _("Gesamtsumme")


class Invoice(WorkspaceScopedModel, BaseModel):
    client = models.ForeignKey("crm.Client", on_delete=models.PROTECT, related_name="invoices")
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )

    status = models.CharField(
        max_length=20,
        choices=InvoiceStatus.choices,
        default=InvoiceStatus.DRAFT_LOCAL,
        db_index=True,
    )

    # Lexware-assigned, read-only once set. Empty until finalised there.
    invoice_number = models.CharField(max_length=50, blank=True)

    title = models.CharField(max_length=200, default="Rechnung")
    introduction = models.TextField(blank=True)
    remark = models.TextField(blank=True)

    invoice_date = models.DateField(null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    payment_term_days = models.PositiveSmallIntegerField(default=14)

    tax_type = models.CharField(max_length=20, choices=TaxType.choices, default=TaxType.NET)
    tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("19.00"),
        help_text=_("Regelsteuersatz; bei Kleinunternehmer 0."),
    )
    currency = models.CharField(max_length=3, default="EUR")

    # Snapshot of the composed period (min/max of the selected entries).
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)

    # Computed from lines; stored so the mirror survives without a recompute and
    # so Lexware-synced totals can overwrite ours.
    net_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    open_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_at = models.DateField(null=True, blank=True)

    # Lexware mirror fields (populated once connected).
    lexware_version = models.IntegerField(null=True, blank=True)
    pdf_file = models.ForeignKey(
        "files.StoredFile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    grouping = models.CharField(
        max_length=20, choices=InvoiceGrouping.choices, default=InvoiceGrouping.PER_SERVICE
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["workspace", "status", "-created_at"]),
            models.Index(fields=["client", "status"]),
        ]

    def __str__(self) -> str:
        return self.invoice_number or f"Entwurf {str(self.pk)[:8]}"

    @property
    def is_cancelled(self) -> bool:
        return self.status in CANCELLED_STATUSES

    @property
    def is_editable(self) -> bool:
        """Only local drafts can still be recomposed; once at Lexware it is frozen."""
        return self.status == InvoiceStatus.DRAFT_LOCAL

    def recompute_totals(self) -> None:
        """Recalculate net/tax/gross from lines. Rounds once per total."""
        from apps.core.money import money

        net = sum((line.total_price for line in self.lines.all()), Decimal("0.00"))
        net = money(net)
        if self.tax_type == TaxType.VATFREE:
            tax = Decimal("0.00")
        else:
            tax = money(net * self.tax_rate / Decimal("100"))
        self.net_amount = net
        self.tax_amount = tax
        self.gross_amount = money(net + tax)
        # open_amount is Lexware's to set once finalised; until then it tracks gross.
        if self.status in (InvoiceStatus.DRAFT_LOCAL, InvoiceStatus.DRAFT_REMOTE):
            self.open_amount = self.gross_amount


class InvoiceLine(WorkspaceScopedModel, BaseModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit = models.CharField(max_length=30, default="Std.")
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("19.00"))
    total_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "created_at"]

    def __str__(self) -> str:
        return self.title

    def recompute(self) -> None:
        from apps.core.money import money

        self.total_price = money(self.quantity * self.unit_price)


class InvoiceTimeEntry(WorkspaceScopedModel, BaseModel):
    """Links a time entry to the invoice line it was billed on.

    The partial unique index below is the **real** double-billing guarantee: a
    time entry may belong to at most one non-cancelled invoice. A status check
    alone races; this cannot. See docs/integrations/lexware.md §6.3.
    """

    invoice_line = models.ForeignKey(
        InvoiceLine, on_delete=models.CASCADE, related_name="time_entries"
    )
    invoice = models.ForeignKey(
        Invoice, on_delete=models.CASCADE, related_name="invoice_time_entries"
    )
    time_entry = models.ForeignKey(
        "timetracking.TimeEntry", on_delete=models.PROTECT, related_name="invoice_links"
    )
    duration_seconds_taken = models.PositiveIntegerField()
    amount_taken = models.DecimalField(max_digits=12, decimal_places=2)
    # Denormalised so the partial unique index can reference it — a FK to the
    # invoice's status is not indexable directly.
    invoice_cancelled = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["time_entry"],
                condition=models.Q(invoice_cancelled=False),
                name="one_active_invoice_per_time_entry",
            ),
        ]
        indexes = [models.Index(fields=["invoice", "invoice_cancelled"])]

    def __str__(self) -> str:
        return f"{self.time_entry_id} → {self.invoice_id}"
