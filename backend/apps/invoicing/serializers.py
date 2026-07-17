"""Invoice serializers."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.api import WorkspaceScopedSerializer
from apps.invoicing.models import Invoice, InvoiceLine


class InvoiceLineSerializer(WorkspaceScopedSerializer):
    class Meta:
        model = InvoiceLine
        fields = [
            "id",
            "title",
            "description",
            "quantity",
            "unit",
            "unit_price",
            "tax_rate",
            "total_price",
            "order",
        ]
        read_only_fields = ["id", "total_price"]


class InvoiceListSerializer(WorkspaceScopedSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "client_name",
            "project",
            "status",
            "status_display",
            "invoice_number",
            "invoice_date",
            "due_date",
            "net_amount",
            "tax_amount",
            "gross_amount",
            "open_amount",
            "currency",
            "period_start",
            "period_end",
            "created_at",
        ]
        read_only_fields = fields


class InvoiceDetailSerializer(WorkspaceScopedSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)
    is_editable = serializers.BooleanField(read_only=True)
    entry_count = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "client_name",
            "project",
            "status",
            "status_display",
            "invoice_number",
            "title",
            "introduction",
            "remark",
            "invoice_date",
            "due_date",
            "payment_term_days",
            "tax_type",
            "tax_rate",
            "currency",
            "grouping",
            "period_start",
            "period_end",
            "net_amount",
            "tax_amount",
            "gross_amount",
            "open_amount",
            "paid_at",
            "lexware_version",
            "last_synced_at",
            "lines",
            "is_editable",
            "entry_count",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "invoice_number",
            "net_amount",
            "tax_amount",
            "gross_amount",
            "open_amount",
            "paid_at",
            "lexware_version",
            "last_synced_at",
            "created_at",
            "updated_at",
        ]

    def get_entry_count(self, obj: Invoice) -> int:
        return obj.invoice_time_entries.count()


class ComposeInvoiceSerializer(serializers.Serializer[dict[str, Any]]):
    """Input for building a draft from selected time entries."""

    client = serializers.UUIDField()
    project = serializers.UUIDField(required=False, allow_null=True)
    entry_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=False)
    grouping = serializers.ChoiceField(
        choices=[
            "per_entry",
            "per_day",
            "per_service",
            "per_phase",
            "per_task",
            "lump_sum",
        ],
        default="per_service",
    )
    tax_type = serializers.ChoiceField(
        choices=["net", "gross", "vatfree"], required=False, allow_null=True
    )
    payment_term_days = serializers.IntegerField(required=False, min_value=0, max_value=180)


class InvoiceLineInputSerializer(serializers.Serializer[dict[str, Any]]):
    """Line input for editing a draft. Unlike the read serializer, ``id`` is
    writable here so existing lines can be matched and updated in place."""

    id = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=300)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit = serializers.CharField(max_length=30, default="Std.")
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    tax_rate = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)


class InvoiceUpdateSerializer(serializers.Serializer[dict[str, Any]]):
    """Editable fields on a local draft (header + lines)."""

    title = serializers.CharField(required=False, max_length=200)
    introduction = serializers.CharField(required=False, allow_blank=True)
    remark = serializers.CharField(required=False, allow_blank=True)
    invoice_date = serializers.DateField(required=False, allow_null=True)
    payment_term_days = serializers.IntegerField(required=False, min_value=0, max_value=180)
    tax_type = serializers.ChoiceField(choices=["net", "gross", "vatfree"], required=False)
    lines = InvoiceLineInputSerializer(many=True, required=False)
