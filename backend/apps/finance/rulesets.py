"""Default German tax rulesets.

These encode the statutory parameters as *data* (§32a EStG tariff zones, VAT
rates, Gewerbesteuer figures) with a source note per value. They are installed
idempotently by the finance seeder and can be edited or superseded by a new
version without touching calculation code.

The 2025 and 2026 figures mirror the enacted tariff.  Corrections are shipped as
new rule versions so an old snapshot remains reproducible.
"""

from __future__ import annotations

from datetime import date
from typing import Any

# §32a EStG 2025 income tax tariff — the piecewise polynomial as data.
_TARIFF_2025 = [
    {"type": "zero", "up_to": 12096},
    {"type": "progressive", "up_to": 17443, "base": 12096, "a": 932.30, "b": 1400, "c": 0},
    {"type": "progressive", "up_to": 68480, "base": 17443, "a": 176.64, "b": 2397, "c": 1015.13},
    {"type": "linear", "up_to": 277825, "rate": 0.42, "subtract": 10911.92},
    {"type": "linear", "up_to": None, "rate": 0.45, "subtract": 19246.67},
]

# §32a EStG 2026.
_TARIFF_2026 = [
    {"type": "zero", "up_to": 12348},
    {"type": "progressive", "up_to": 17799, "base": 12348, "a": 914.51, "b": 1400, "c": 0},
    {"type": "progressive", "up_to": 69878, "base": 17799, "a": 173.10, "b": 2397, "c": 1034.87},
    {"type": "linear", "up_to": 277825, "rate": 0.42, "subtract": 11135.63},
    {"type": "linear", "up_to": None, "rate": 0.45, "subtract": 19470.38},
]

_COMMON: dict[str, Any] = {
    "vat_standard_rate": 19,
    "vat_reduced_rate": 7,
    "trade_tax_base_rate": 3.5,  # Steuermesszahl
    "trade_tax_allowance": 24500,  # Freibetrag für natürliche Personen
    "trade_tax_credit_factor": 4.0,  # §35 EStG
    "corporate_tax_rate": 15,  # §23 KStG (through 2027)
    "soli_rate": 5.5,
}


def _sources(year: int, provisional: bool) -> list[dict[str, str]]:
    note = "vorläufig — vor Nutzung prüfen" if provisional else "bestätigt"
    return [
        {"field": "income_tax_zones", "source": f"§32a EStG {year}", "note": note},
        {"field": "vat_standard_rate", "source": "§12 UStG", "note": "19%"},
        {
            "field": "trade_tax_allowance",
            "source": "§11 GewStG",
            "note": "24.500 € (nat. Personen)",
        },
        {
            "field": "trade_tax_credit_factor",
            "source": "§35 EStG",
            "note": "4-fache des Messbetrags",
        },
        {"field": "corporate_tax_rate", "source": "§23 KStG", "note": "15%"},
        {"field": "soli_rate", "source": "SolzG", "note": "5,5% über Freigrenze"},
    ]


DEFAULT_RULESETS: list[dict[str, Any]] = [
    {
        "tax_year": 2025,
        "rule_version": "2",
        "valid_from": date(2025, 1, 1),
        "config": {
            **_COMMON,
            "income_tax_zones": _TARIFF_2025,
            "soli_free_limit": 19950,  # ESt-Freigrenze Soli 2025 (Einzelveranlagung)
        },
        "sources": _sources(2025, provisional=False),
    },
    {
        "tax_year": 2026,
        "rule_version": "2",
        "valid_from": date(2026, 1, 1),
        "config": {
            **_COMMON,
            "income_tax_zones": _TARIFF_2026,
            "soli_free_limit": 20350,
        },
        "sources": _sources(2026, provisional=False),
    },
]


def install_default_rulesets() -> int:
    """Install the shipped rulesets idempotently. Returns how many were new.

    Rulesets are global (not workspace-scoped) and versioned; existing rows are
    never overwritten — corrections ship as a new ``rule_version``.
    """
    from apps.finance.models import TaxRuleSet

    installed = 0
    for spec in DEFAULT_RULESETS:
        _, created = TaxRuleSet.objects.get_or_create(
            tax_year=spec["tax_year"],
            rule_version=spec["rule_version"],
            defaults={
                "valid_from": spec["valid_from"],
                "config": spec["config"],
                "sources": spec["sources"],
            },
        )
        installed += int(created)
    return installed
