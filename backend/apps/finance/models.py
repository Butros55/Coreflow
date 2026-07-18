"""Tax profile, versioned tax rules, and reserve snapshots.

The tax calculation is deliberately data-driven: rates live in a versioned,
sourced ``TaxRuleSet`` (JSON), never hardcoded in a function. A rate baked into
code is one nobody can audit and is silently wrong the year it changes.

Every forecast carries the disclaimer that it is unverbindlich and no substitute
for tax advice.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, WorkspaceScopedModel

DISCLAIMER = "Unverbindliche Prognose. Kein Ersatz für eine steuerliche Beratung."


class LegalForm(models.TextChoices):
    SOLE = "sole", _("Einzelunternehmen")
    FREELANCER = "freelancer", _("Freiberufler")
    UG = "ug", _("UG (haftungsbeschränkt)")
    GMBH = "gmbh", _("GmbH")


class HealthInsuranceStatus(models.TextChoices):
    STATUTORY_VOLUNTARY = "statutory_voluntary", _("Freiwillig gesetzlich")
    PRIVATE = "private", _("Privat")
    FAMILY = "family", _("Familienversichert")


class TaxProfile(WorkspaceScopedModel, BaseModel):
    """The user-editable assumptions behind the forecast.

    One profile per (workspace, tax_year). Everything here is an *assumption* the
    user can override — the forecast shows its work from these inputs.
    """

    tax_year = models.PositiveIntegerField(db_index=True)
    legal_form = models.CharField(max_length=20, choices=LegalForm.choices, default=LegalForm.SOLE)
    small_business = models.BooleanField(default=False, help_text=_("§19 UStG"))

    # Additional taxable household income (e.g. a spouse's, or employment) that
    # raises the marginal rate. Optional.
    other_taxable_income = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    joint_assessment = models.BooleanField(
        default=False, help_text=_("Zusammenveranlagung (Splitting).")
    )

    # Gewerbesteuer (trade tax) — not levied on Freiberufler.
    trade_tax_multiplier = models.PositiveIntegerField(
        default=400, help_text=_("Hebesatz in %, z. B. 400.")
    )

    church_tax = models.BooleanField(default=False)
    federal_state = models.CharField(max_length=2, default="BW", help_text=_("Bundesland-Kürzel."))

    health_insurance_status = models.CharField(
        max_length=24,
        choices=HealthInsuranceStatus.choices,
        default=HealthInsuranceStatus.STATUTORY_VOLUNTARY,
    )
    estimated_monthly_health_insurance = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("450.00")
    )

    # A blanket safety margin the user can dial in on top of the computed reserve.
    safety_margin_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("5.00")
    )
    prepayments_made = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_("Bereits geleistete Steuervorauszahlungen."),
    )
    existing_reserve = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=_("Bereits gebildete Rücklage."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "tax_year"], name="unique_tax_profile_per_year"
            ),
        ]

    def __str__(self) -> str:
        return f"Steuerprofil {self.tax_year}"


class TaxRuleSet(BaseModel):
    """Versioned German tax parameters for a year.

    Not workspace-scoped: these are the law, shared across tenants. Values live
    in ``config`` (JSON) with ``sources`` citing where each came from, so the
    calculation is auditable and a rate change is a data edit, not a code change.
    """

    tax_year = models.PositiveIntegerField(db_index=True)
    rule_version = models.CharField(max_length=20, default="1")
    valid_from = models.DateField()
    config = models.JSONField(help_text=_("Grundfreibetrag, Zonen, USt-Sätze, KV-Sätze, …"))
    sources = models.JSONField(default=list, help_text=_("Quellenhinweise je Wert."))
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ["-tax_year", "-rule_version"]
        constraints = [
            models.UniqueConstraint(
                fields=["tax_year", "rule_version"], name="unique_tax_rule_version"
            ),
        ]

    def __str__(self) -> str:
        return f"Steuerregeln {self.tax_year} v{self.rule_version}"


class ReserveSnapshot(WorkspaceScopedModel, BaseModel):
    """A point-in-time reserve computation, so a trend line is visible over time.

    ``calculation_trace`` stores every step of the derivation — the requirement
    is that the forecast is explainable, and a number without its derivation is
    not.
    """

    snapshot_date = models.DateField(db_index=True)
    tax_year = models.PositiveIntegerField()

    revenue_ytd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    expenses_ytd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    profit_ytd = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    projected_annual_profit = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    estimated_income_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_soli = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_church_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    estimated_trade_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    trade_tax_credit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    vat_reserve = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    health_insurance_buffer = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    safety_buffer = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    recommended_reserve = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    existing_reserve = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserve_gap = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    calculation_trace = models.JSONField(default=dict)
    rule_set = models.ForeignKey(
        TaxRuleSet, on_delete=models.SET_NULL, null=True, related_name="snapshots"
    )

    class Meta:
        ordering = ["-snapshot_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "snapshot_date"],
                name="unique_reserve_snapshot_per_day",
            ),
        ]

    def __str__(self) -> str:
        return f"Rücklage {self.snapshot_date}: {self.recommended_reserve} €"
