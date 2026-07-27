"""Invoice serializers."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.api import WorkspaceScopedSerializer
from apps.invoicing.models import Invoice, InvoiceLine


class InvoiceLineSerializer(WorkspaceScopedSerializer):
    time_entries = serializers.SerializerMethodField()

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
            "time_entries",
        ]
        read_only_fields = ["id", "total_price", "time_entries"]

    def get_time_entries(self, obj: InvoiceLine) -> list[dict[str, Any]]:
        """Active time-entry links of this line, with their origin.

        ``source == "lexware_import"`` marks assignments the Lexware import
        made — the UI badges those so the user can tell them from links the
        local composer created.
        """
        links = getattr(obj, "active_links", None)
        if links is None:  # detail view prefetches; any other path falls back
            links = list(
                obj.time_entries.filter(invoice_cancelled=False).select_related("time_entry")
            )
        return [
            {
                "time_entry_id": str(link.time_entry_id),
                "started_at": link.time_entry.started_at.isoformat(),
                "description": link.time_entry.description,
                "duration_seconds": link.duration_seconds_taken,
                "source": link.source,
            }
            for link in links
        ]


class InvoiceListSerializer(WorkspaceScopedSerializer):
    client_name = serializers.CharField(source="client.display_name", read_only=True)
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "client_name",
            "project",
            "project_name",
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
    project_name = serializers.CharField(source="project.name", read_only=True, default=None)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lines = InvoiceLineSerializer(many=True, read_only=True)
    is_editable = serializers.BooleanField(read_only=True)
    entry_count = serializers.SerializerMethodField()
    lexware_url = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id",
            "client",
            "client_name",
            "project",
            "project_name",
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
            "lexware_url",
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

    def get_lexware_url(self, obj: Invoice) -> str | None:
        """Permalink into the Lexware web app, once the invoice exists there.

        Drafts have no API-renderable PDF (the API answers 406 by design), so
        the UI links the user straight to the voucher instead. Drafts open in
        the editor, finalised invoices in the read view.
        """
        from django.conf import settings

        from apps.integrations.models import ExternalObjectLink, Provider
        from apps.invoicing.models import InvoiceStatus

        link = ExternalObjectLink.objects.filter(
            workspace=obj.workspace,
            provider=Provider.LEXWARE,
            resource_type="invoice",
            local_object_id=obj.pk,
        ).first()
        if link is None:
            return None
        drafts = (InvoiceStatus.DRAFT_REMOTE, InvoiceStatus.SEND_PENDING)
        mode = "edit" if obj.status in drafts else "view"
        base = settings.LEXWARE_APP_BASE_URL.rstrip("/")
        return f"{base}/permalink/invoices/{mode}/{link.external_id}"


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
