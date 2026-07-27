"""Install default tax rulesets and a demo tax profile."""

from __future__ import annotations

from apps.core.seeding import SeedContext, register_seeder
from apps.finance.models import LegalForm, TaxProfile, TaxRuleSet
from apps.finance.rulesets import install_default_rulesets


@register_seeder("finance", order=50)
def seed_finance(ctx: SeedContext) -> str:
    # Rulesets are global (not workspace-scoped); install once, idempotently.
    installed = install_default_rulesets()

    from datetime import date

    profile, _ = TaxProfile.objects.get_or_create(
        workspace=ctx.workspace,
        tax_year=date(2026, 1, 1).year,
        defaults={
            "legal_form": LegalForm.SOLE,
            "small_business": ctx.workspace.small_business,
            "trade_tax_multiplier": 420,
            "federal_state": "BW",
            "estimated_monthly_health_insurance": "480.00",
            "safety_margin_percent": "5.00",
        },
    )
    total = TaxRuleSet.objects.count()
    return f"{total} Steuerregelsätze ({installed} neu), Steuerprofil {profile.tax_year}"
