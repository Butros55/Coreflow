"""Finance serializers (tax profile, reserve snapshots, reserve ledger)."""

from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.core.api import WorkspaceScopedSerializer
from apps.finance.models import ReserveSnapshot, ReserveTransfer, TaxProfile


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


class ReserveTransferSerializer(WorkspaceScopedSerializer):
    source_display = serializers.CharField(source="get_source_display", read_only=True)

    class Meta:
        model = ReserveTransfer
        fields = [
            "id",
            "transfer_date",
            "amount",
            "note",
            "source",
            "source_display",
            "created_at",
        ]
        read_only_fields = ["id", "source", "source_display", "created_at"]

    def validate_amount(self, value: Decimal) -> Decimal:
        if value == 0:
            raise serializers.ValidationError("Betrag darf nicht 0 sein.")
        return value


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
            "estimated_corporate_tax",
            "vat_reserve",
        ]
        read_only_fields = fields
