"""One demo invoice draft, composed from real seeded time entries."""

from __future__ import annotations

from apps.core.seeding import SeedContext, register_seeder
from apps.crm.models import Client
from apps.invoicing.models import Invoice
from apps.invoicing.services import compose_invoice
from apps.timetracking.models import BillingStatus, TimeEntry


@register_seeder("invoicing", order=40)
def seed_invoicing(ctx: SeedContext) -> str:
    if Invoice.objects.filter(workspace=ctx.workspace).exists():
        count = Invoice.objects.filter(workspace=ctx.workspace).count()
        return f"{count} Rechnungen (bereits vorhanden, übersprungen)"

    # Compose a draft for the client with the most open billable hours, so the
    # invoices page and the client's Rechnungen tab both show something real.
    client = (
        Client.objects.filter(workspace=ctx.workspace, status="active")
        .order_by("name")
        .first()
    )
    if client is None:
        return "keine Kunden — übersprungen"

    open_entries = list(
        TimeEntry.objects.filter(
            workspace=ctx.workspace,
            client=client,
            billable=True,
            billing_status=BillingStatus.OPEN,
            ended_at__isnull=False,
        ).order_by("started_at")[:8]
    )
    if not open_entries:
        return "keine offenen Zeiten — übersprungen"

    invoice = compose_invoice(
        workspace=ctx.workspace,
        client=client,
        entry_ids=[str(e.id) for e in open_entries],
        grouping="per_service",
    )
    ctx.record("invoices", 1)
    return f"1 Rechnungsentwurf für {client.name} ({invoice.gross_amount} €)"
