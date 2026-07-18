"""The full business journey, end to end through the real API surface.

Client → project → tracked time (timer + manual) → open-entries picker →
composed draft → Lexware draft (mocked — no sandbox exists) → remote
finalisation + payment sync → entries billed → double-billing blocked →
finance dashboard shows the revenue → audit trail complete.

Every step goes through URLs, serializers, permissions and services exactly as
the browser would drive them. The only fakes are the provider HTTP responses.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import respx
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Workspace
from apps.core.audit import AuditLogEntry
from apps.integrations.base import TokenBucketLimiter
from apps.integrations.lexware.tasks import sync_invoice_statuses
from apps.invoicing.models import Invoice, InvoiceStatus
from apps.timetracking.models import BillingStatus, TimeEntry

pytestmark = pytest.mark.django_db

LEXWARE = "https://api.lexware.io"


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(TokenBucketLimiter, "acquire", lambda self: None)


class TestFullJourney:
    @respx.mock
    @override_settings(LEXWARE_ENABLED=True, LEXWARE_API_KEY="journey-key")
    def test_client_to_paid_invoice(self, auth_client: APIClient, workspace: Workspace) -> None:
        # -- 1. Create the client through the API ---------------------------
        created = auth_client.post(
            reverse("client-list"),
            {"name": "Journey GmbH", "default_hourly_rate": "120.00"},
            format="json",
        )
        assert created.status_code == 201
        client_id = created.data["id"]
        assert created.data["client_number"].startswith("K-")  # auto-assigned

        # -- 2. A project underneath it -------------------------------------
        project = auth_client.post(
            reverse("project-list"),
            {"name": "Relaunch", "client": client_id},
            format="json",
        )
        assert project.status_code == 201

        # -- 3. Track time: run the timer, then add a manual entry ----------
        start = auth_client.post(
            reverse("time-entry-start-timer"),
            {"client": client_id, "description": "Kickoff"},
            format="json",
        )
        assert start.status_code == 201
        running_id = start.data["id"]

        # Backdate the running entry so the stop yields a real duration.
        TimeEntry.objects.filter(pk=running_id).update(
            started_at=timezone.now() - timedelta(hours=2)
        )
        stop = auth_client.post(reverse("time-entry-stop-timer"), format="json")
        assert stop.status_code == 200

        manual = auth_client.post(
            reverse("time-entry-list"),
            {
                "client": client_id,
                "started_at": (timezone.now() - timedelta(days=1)).isoformat(),
                "duration_input_seconds": 5400,
                "description": "Konzeption",
            },
            format="json",
        )
        assert manual.status_code == 201

        # -- 4. Both entries appear in the open-entries picker ---------------
        open_entries = auth_client.get(reverse("open-entry-list"))
        picker = {c["client_id"]: c for c in open_entries.data["clients"]}
        assert client_id in picker
        entry_ids = [e["id"] for e in picker[client_id]["entries"]]
        assert len(entry_ids) == 2

        # -- 5. Compose the local draft --------------------------------------
        composed = auth_client.post(
            reverse("invoice-list"),
            {"client": client_id, "entry_ids": entry_ids, "grouping": "per_service"},
            format="json",
        )
        assert composed.status_code == 201
        invoice_id = composed.data["id"]
        assert composed.data["status"] == InvoiceStatus.DRAFT_LOCAL
        # 2h timer + 1.5h manual at the client rate of 120 €.
        assert Decimal(composed.data["net_amount"]) == Decimal("420.00")

        # Entries are now reserved — recomposing them must fail.
        double = auth_client.post(
            reverse("invoice-list"),
            {"client": client_id, "entry_ids": entry_ids, "grouping": "lump_sum"},
            format="json",
        )
        assert double.status_code in (400, 409)

        # -- 6. Send to Lexware (draft by default) ---------------------------
        respx.post(f"{LEXWARE}/v1/invoices").mock(
            return_value=httpx.Response(
                201, json={"id": "lex-journey-1", "resourceUri": "…", "version": 1}
            )
        )
        respx.get(f"{LEXWARE}/v1/invoices/lex-journey-1").mock(
            return_value=httpx.Response(
                200,
                json={"id": "lex-journey-1", "voucherStatus": "draft", "version": 1},
            )
        )
        sent = auth_client.post(reverse("invoice-send", args=[invoice_id]), format="json")
        assert sent.status_code == 200
        assert sent.data["status"] == InvoiceStatus.DRAFT_REMOTE

        # Entries stay in draft state until the invoice is finalised remotely.
        statuses = set(
            TimeEntry.objects.filter(pk__in=entry_ids).values_list("billing_status", flat=True)
        )
        assert statuses == {BillingStatus.DRAFT_CREATED}

        # -- 7. Lexware finalises and the customer pays; the sync mirrors it -
        respx.get(f"{LEXWARE}/v1/invoices/lex-journey-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": "lex-journey-1",
                    "voucherStatus": "paid",
                    "voucherNumber": "RE-2026-0042",
                    "voucherDate": "2026-07-16",
                    "version": 2,
                    "totalPrice": {
                        "totalNetAmount": 420.0,
                        "totalTaxAmount": 79.8,
                        "totalGrossAmount": 499.8,
                    },
                },
            )
        )
        respx.get(f"{LEXWARE}/v1/payments/lex-journey-1").mock(
            return_value=httpx.Response(
                200,
                json={"paymentStatus": "balanced", "openAmount": 0, "paidDate": "2026-07-17"},
            )
        )
        summary = sync_invoice_statuses(workspace)
        assert summary == {"updated": 1, "failed": 0}

        invoice = Invoice.objects.get(pk=invoice_id)
        assert invoice.status == InvoiceStatus.PAID
        assert invoice.invoice_number == "RE-2026-0042"  # Lexware assigns numbers
        assert invoice.invoice_date is not None  # mirrored voucherDate
        assert invoice.paid_at is not None

        # Entries settle to billed…
        statuses = set(
            TimeEntry.objects.filter(pk__in=entry_ids).values_list("billing_status", flat=True)
        )
        assert statuses == {BillingStatus.BILLED}
        # …and the picker no longer offers them.
        after = auth_client.get(reverse("open-entry-list"))
        assert client_id not in {c["client_id"] for c in after.data["clients"]}

        # -- 8. The finance dashboard sees the revenue -----------------------
        dashboard = auth_client.get(reverse("finance:dashboard"))
        assert dashboard.status_code == 200
        assert Decimal(dashboard.data["kpis"]["revenue_ytd"]) >= Decimal("420.00")

        # -- 9. The audit trail recorded the send ----------------------------
        assert AuditLogEntry.objects.filter(
            action="invoice.sent", target_id=str(invoice_id)
        ).exists()
