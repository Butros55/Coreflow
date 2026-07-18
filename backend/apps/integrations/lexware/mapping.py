"""Map a local Invoice to the Lexware create-invoice payload.

Every field here comes from the verified structure in
docs/integrations/lexware.md §4.3. No field is invented. Read-only fields
(totals, taxAmounts, voucherNumber, dueDate) are deliberately omitted — Lexware
rejects a payload that includes them.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from apps.invoicing.models import Invoice, TaxType

# Lexware datetime: exactly yyyy-MM-ddTHH:mm:ss.SSSXXX. We use midnight UTC+01/02
# is not required — a plain date at midnight with a +01:00 offset is accepted;
# we send UTC 'Z'-style with milliseconds to satisfy the strict parser.
_DT_SUFFIX = "T00:00:00.000+01:00"


def _date(value: Any) -> str:
    return f"{value.isoformat()}{_DT_SUFFIX}"


def invoice_to_lexware_payload(invoice: Invoice) -> dict[str, Any]:
    """Build the POST /v1/invoices body for a local draft.

    The address is sent as a one-time address (name + countryCode) unless the
    client is linked to a Lexware contact, in which case contactId is used and
    the contact's billing address applies.
    """
    address = _build_address(invoice)

    line_items = [_line_item(line, invoice.tax_type) for line in invoice.lines.all()]

    term_label = f"Zahlbar innerhalb von {invoice.payment_term_days} Tagen ohne Abzug."

    payload: dict[str, Any] = {
        "archived": False,
        "voucherDate": _date(invoice.invoice_date or invoice.period_end),
        "address": address,
        "lineItems": line_items,
        # Only currency is allowed on create; totals are read-only.
        "totalPrice": {"currency": invoice.currency},
        "taxConditions": _tax_conditions(invoice),
        # We bill work over a period → serviceperiod with the tracked range.
        "shippingConditions": {
            "shippingDate": _date(invoice.period_start or invoice.invoice_date),
            "shippingEndDate": _date(invoice.period_end or invoice.invoice_date),
            "shippingType": "serviceperiod",
        },
        "title": invoice.title,
        "introduction": invoice.introduction,
        "remark": invoice.remark,
        "paymentConditions": {
            "paymentTermLabel": term_label,
            "paymentTermDuration": invoice.payment_term_days,
        },
    }
    return payload


def _build_address(invoice: Invoice) -> dict[str, Any]:
    from apps.integrations.models import ExternalObjectLink, Provider

    client = invoice.client
    link = ExternalObjectLink.objects.filter(
        workspace_id=invoice.workspace_id,
        provider=Provider.LEXWARE,
        resource_type="contact",
        local_object_id=client.pk,
    ).first()
    if link:
        # Reference the Lexware contact; its billing address is used.
        return {"contactId": link.external_id}
    # One-time address: name + countryCode required.
    address: dict[str, Any] = {
        "name": client.name,
        "countryCode": client.billing_country_code or "DE",
    }
    if client.billing_street:
        address["street"] = client.billing_street
    if client.billing_zip:
        address["zip"] = client.billing_zip
    if client.billing_city:
        address["city"] = client.billing_city
    return address


def _line_item(line: Any, tax_type: str) -> dict[str, Any]:
    """A 'custom' line item — we do not reference Lexware articles."""
    unit_price: dict[str, Any] = {
        "currency": "EUR",
        # Vat-free invoices REQUIRE 0 here (lexware.md §4.4) — enforced at the
        # wire regardless of what the stored line carries, because a draft
        # switched to vatfree after composition may still hold stale rates and
        # Lexware then rejects with "line items … must not contain taxes".
        "taxRatePercentage": 0 if tax_type == TaxType.VATFREE else _num(line.tax_rate),
    }
    # For net invoices Lexware wants netAmount; for gross, grossAmount.
    if tax_type == TaxType.GROSS:
        unit_price["grossAmount"] = _num(line.unit_price)
    else:
        unit_price["netAmount"] = _num(line.unit_price)

    return {
        "type": "custom",
        "name": line.title,
        "description": line.description,
        "quantity": _num(line.quantity),
        "unitName": line.unit,
        "unitPrice": unit_price,
        "discountPercentage": 0,
    }


def _tax_conditions(invoice: Invoice) -> dict[str, Any]:
    if invoice.tax_type == TaxType.VATFREE:
        return {
            "taxType": "vatfree",
            "taxTypeNote": "Gemäß § 19 UStG wird keine Umsatzsteuer berechnet.",
        }
    return {"taxType": invoice.tax_type}


def _num(value: Decimal) -> float:
    """Lexware accepts JSON numbers; Decimal is not JSON-serialisable.

    We round to 4 places (Lexware's max for amounts) then hand over a float.
    The authoritative Decimal stays on our side; this is only the wire value.
    """
    return float(value)


def apply_lexware_invoice(invoice: Invoice, remote: dict[str, Any]) -> None:
    """Copy finalised Lexware fields back onto the local mirror.

    Called after creation and on invoice.* webhooks. Only Lexware-owned fields
    are touched — number, status, totals, dates — never our composition.
    """
    from apps.core.money import money
    from apps.invoicing.models import InvoiceStatus

    status_map = {
        "draft": InvoiceStatus.DRAFT_REMOTE,
        "open": InvoiceStatus.OPEN,
        "paid": InvoiceStatus.PAID,
        "voided": InvoiceStatus.VOIDED,
    }
    remote_status = remote.get("voucherStatus")
    if remote_status in status_map:
        invoice.status = status_map[remote_status]

    if remote.get("voucherNumber"):
        invoice.invoice_number = remote["voucherNumber"]
    if remote.get("version") is not None:
        invoice.lexware_version = remote["version"]

    # Lexware owns the voucher date; without this mirror a finalised invoice
    # kept a NULL invoice_date and silently dropped out of the revenue KPIs.
    if remote.get("voucherDate"):
        try:
            invoice.invoice_date = dt.date.fromisoformat(str(remote["voucherDate"])[:10])
        except ValueError:
            pass

    total = remote.get("totalPrice") or {}
    if total.get("totalNetAmount") is not None:
        invoice.net_amount = money(Decimal(str(total["totalNetAmount"])))
    if total.get("totalTaxAmount") is not None:
        invoice.tax_amount = money(Decimal(str(total["totalTaxAmount"])))
    if total.get("totalGrossAmount") is not None:
        invoice.gross_amount = money(Decimal(str(total["totalGrossAmount"])))
