"""Invoice API: compose from time entries, edit draft, send to Lexware."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from rest_framework import status as http_status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.api import WorkspaceScopedViewSet
from apps.core.money import money
from apps.invoicing.models import Invoice, InvoiceLine, InvoiceStatus
from apps.invoicing.serializers import (
    ComposeInvoiceSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    InvoiceUpdateSerializer,
)
from apps.invoicing.services import (
    InvoiceCompositionError,
    cancel_invoice,
    compose_invoice,
    preview_lines,
)
from apps.timetracking.models import BillingStatus, TimeEntry


class InvoiceViewSet(WorkspaceScopedViewSet):
    queryset = Invoice.objects.select_related("client", "project").prefetch_related("lines")
    serializer_class = InvoiceDetailSerializer
    filterset_fields = {"client": ["exact"], "status": ["exact"], "project": ["exact"]}
    search_fields = ["invoice_number", "client__name", "title"]
    ordering_fields = ["created_at", "invoice_date", "gross_amount", "status"]
    ordering = ["-created_at"]
    # No plain create: invoices are composed from time entries, not POSTed raw.
    http_method_names = ["get", "patch", "head", "options", "post", "delete"]

    def get_serializer_class(self) -> type[Any]:
        if self.action == "list":
            return InvoiceListSerializer
        return InvoiceDetailSerializer

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Compose a local-draft invoice from selected open time entries."""
        serializer = ComposeInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace = self.get_workspace()
        assert workspace is not None

        from apps.crm.models import Client

        client = Client.objects.filter(workspace=workspace, pk=data["client"]).first()
        if client is None:
            return Response(
                {"error": {"code": "not_found", "message": "Kunde nicht gefunden."}},
                status=http_status.HTTP_404_NOT_FOUND,
            )
        try:
            invoice = compose_invoice(
                workspace=workspace,
                client=client,
                entry_ids=[str(x) for x in data["entry_ids"]],
                grouping=data["grouping"],
                project_id=str(data["project"]) if data.get("project") else None,
                tax_type=data.get("tax_type"),
                payment_term_days=data.get("payment_term_days"),
            )
        except InvoiceCompositionError as exc:
            return Response(
                {"error": {"code": "composition_error", "message": str(exc)}},
                status=http_status.HTTP_409_CONFLICT,
            )
        return Response(
            InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data,
            status=http_status.HTTP_201_CREATED,
        )

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        invoice = self.get_object()
        if not invoice.is_editable:
            return Response(
                {
                    "error": {
                        "code": "not_editable",
                        "message": "Nur lokale Entwürfe können bearbeitet werden.",
                    }
                },
                status=http_status.HTTP_409_CONFLICT,
            )
        serializer = InvoiceUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        with transaction.atomic():
            for field in (
                "title",
                "introduction",
                "remark",
                "invoice_date",
                "payment_term_days",
                "tax_type",
            ):
                if field in data:
                    setattr(invoice, field, data[field])
            if "tax_type" in data:
                from apps.invoicing.models import TaxType

                invoice.tax_rate = (
                    invoice.tax_rate if data["tax_type"] != TaxType.VATFREE else money("0")
                )

            if "lines" in data:
                # Replace lines wholesale — simplest correct semantics for an edit.
                # Time-entry links stay attached to the invoice, not the line, so
                # replacing lines does not release entries.
                existing = {str(line.id): line for line in invoice.lines.all()}
                seen: set[str] = set()
                for order, line_data in enumerate(data["lines"]):
                    line_id = str(line_data.get("id") or "")
                    line = existing.get(line_id) or InvoiceLine(
                        workspace=invoice.workspace, invoice=invoice
                    )
                    line.title = line_data.get("title", line.title)
                    line.description = line_data.get("description", line.description)
                    line.quantity = line_data.get("quantity", line.quantity)
                    line.unit = line_data.get("unit", line.unit)
                    line.unit_price = line_data.get("unit_price", line.unit_price)
                    line.tax_rate = line_data.get("tax_rate", invoice.tax_rate)
                    line.order = order
                    line.recompute()
                    line.save()
                    if line_id:
                        seen.add(line_id)
                # Delete removed lines.
                for line_id, line in existing.items():
                    if line_id not in seen:
                        line.delete()

            invoice.recompute_totals()
            invoice.save()

        return Response(
            InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data
        )

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """Cancel a draft and release its time entries back to 'open'."""
        invoice = self.get_object()
        try:
            cancel_invoice(invoice)
        except InvoiceCompositionError as exc:
            return Response(
                {"error": {"code": "not_cancellable", "message": str(exc)}},
                status=http_status.HTTP_409_CONFLICT,
            )
        return Response(status=http_status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="preview")
    def preview(self, request: Request) -> Response:
        """Preview the lines a selection would produce, without persisting."""
        serializer = ComposeInvoiceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace = self.get_workspace()
        assert workspace is not None

        entries = list(
            TimeEntry.objects.filter(
                workspace=workspace, pk__in=[str(x) for x in data["entry_ids"]]
            ).select_related("service_type", "phase", "task")
        )
        drafts = preview_lines(entries, data["grouping"])
        lines = [
            {
                "title": draft.title,
                "hours": str(draft.hours()),
                "amount": str(money(sum((e.computed_amount for e in draft.entries), money("0")))),
                "entry_count": len(draft.entries),
            }
            for draft in drafts
        ]
        total = money(sum((e.computed_amount for e in entries), money("0")))
        return Response({"lines": lines, "total": str(total), "entry_count": len(entries)})

    @action(detail=True, methods=["post"], url_path="send")
    def send(self, request: Request, pk: str | None = None) -> Response:
        """Send a local draft to Lexware as a draft invoice.

        When Lexware is disabled, this is a documented no-op that returns a clear
        error — the local draft remains fully usable.
        """
        from apps.integrations.lexware.client import is_lexware_enabled
        from apps.integrations.lexware.invoicing import send_invoice_to_lexware

        invoice = self.get_object()
        if invoice.status != InvoiceStatus.DRAFT_LOCAL:
            return Response(
                {
                    "error": {
                        "code": "already_sent",
                        "message": "Diese Rechnung wurde bereits übertragen.",
                    }
                },
                status=http_status.HTTP_409_CONFLICT,
            )
        if not is_lexware_enabled():
            return Response(
                {
                    "error": {
                        "code": "integration_disabled",
                        "message": "Lexware ist nicht aktiviert. Entwurf bleibt lokal erhalten. "
                        "Aktiviere Lexware in den Einstellungen.",
                    }
                },
                status=http_status.HTTP_409_CONFLICT,
            )
        try:
            send_invoice_to_lexware(invoice)
        except Exception as exc:
            return Response(
                {"error": {"code": "lexware_error", "message": str(exc)}},
                status=http_status.HTTP_502_BAD_GATEWAY,
            )
        return Response(
            InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data
        )


class OpenTimeEntriesView(WorkspaceScopedViewSet):
    """Open, billable time entries grouped by client — the invoice picker source."""

    queryset = TimeEntry.objects.none()  # overridden below
    http_method_names = ["get", "head", "options"]

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        workspace = self.get_workspace()
        if workspace is None:
            return Response({"clients": []})

        client_id = request.query_params.get("client")
        entries = (
            TimeEntry.objects.filter(
                workspace=workspace,
                billable=True,
                billing_status=BillingStatus.OPEN,
                ended_at__isnull=False,
            )
            .select_related("client", "project", "service_type")
            .order_by("client__name", "started_at")
        )
        if client_id:
            entries = entries.filter(client_id=client_id)

        by_client: dict[str, dict[str, Any]] = {}
        for entry in entries:
            bucket = by_client.setdefault(
                str(entry.client_id),
                {
                    "client_id": str(entry.client_id),
                    "client_name": entry.client.display_name,
                    "currency": entry.client.currency,
                    "entries": [],
                    "total_seconds": 0,
                    "total_amount": money("0"),
                },
            )
            bucket["entries"].append(
                {
                    "id": str(entry.id),
                    "started_at": entry.started_at.isoformat(),
                    "description": entry.description,
                    "project_name": entry.project.name if entry.project else None,
                    "service_type_name": entry.service_type.name if entry.service_type else None,
                    "duration_seconds": entry.duration_seconds,
                    "amount": str(entry.computed_amount),
                }
            )
            bucket["total_seconds"] += entry.duration_seconds
            bucket["total_amount"] += entry.computed_amount

        clients = []
        for bucket in by_client.values():
            bucket["total_amount"] = str(money(bucket["total_amount"]))
            clients.append(bucket)
        return Response({"clients": clients})
