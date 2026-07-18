"""Finance serializers (tax profile + reserve snapshots)."""

from __future__ import annotations

from apps.core.api import WorkspaceScopedSerializer
from apps.finance.models import ReserveSnapshot, TaxProfile


class TaxProfileSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = TaxProfile
        fields = [
            "id",
            "tax_year",
            "legal_form",
            "small_business",
            "other_taxable_income",
            "joint_assessment",
            "trade_tax_multiplier",
            "church_tax",
            "federal_state",
            "health_insurance_status",
            "estimated_monthly_health_insurance",
            "safety_margin_percent",
            "prepayments_made",
            "existing_reserve",
        ]
        read_only_fields = ["id"]


class ReserveSnapshotSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = ReserveSnapshot
        fields = [
            "id",
            "snapshot_date",
            "tax_year",
            "profit_ytd",
            "projected_annual_profit",
            "recommended_reserve",
            "existing_reserve",
            "reserve_gap",
            "estimated_income_tax",
            "vat_reserve",
        ]
        read_only_fields = fields
