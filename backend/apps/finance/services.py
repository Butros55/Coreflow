"""Finance aggregation: KPIs, cashflow vs accrual, and the reserve forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Max, Q, Sum
from django.utils import timezone

from apps.core.money import money
from apps.finance.models import (
    DISCLAIMER,
    ReserveSnapshot,
    ReserveTransfer,
    TaxProfile,
    TaxRuleSet,
)
from apps.finance.tax import compute_taxes
from apps.invoicing.models import Invoice, InvoiceStatus
from apps.timetracking.models import BillingStatus, TimeEntry

CHURCH_TAX_STATES_8 = frozenset({"BW", "BY"})  # 8%; rest 9%


@dataclass
class FinanceKPIs:
    revenue_ytd: Decimal
    revenue_month: Decimal
    revenue_quarter: Decimal
    open_receivables: Decimal
    overdue_receivables: Decimal
    draft_total: Decimal
    unbilled_seconds: int
    unbilled_value: Decimal
    invoiced_total: Decimal
    paid_total: Decimal
    vat_invoiced_ytd: Decimal

    def as_dict(self) -> dict[str, Any]:
        return {
            "revenue_ytd": str(self.revenue_ytd),
            "revenue_month": str(self.revenue_month),
            "revenue_quarter": str(self.revenue_quarter),
            "open_receivables": str(self.open_receivables),
            "overdue_receivables": str(self.overdue_receivables),
            "draft_total": str(self.draft_total),
            "unbilled_seconds": self.unbilled_seconds,
            "unbilled_value": str(self.unbilled_value),
            "invoiced_total": str(self.invoiced_total),
            "paid_total": str(self.paid_total),
            "vat_invoiced_ytd": str(self.vat_invoiced_ytd),
        }


def _year_bounds(year: int) -> tuple[date, date]:
    return date(year, 1, 1), date(year, 12, 31)


def compute_kpis(workspace: Any, today: date | None = None) -> FinanceKPIs:
    today = today or timezone.localdate()
    year_start, _ = _year_bounds(today.year)
    month_start = today.replace(day=1)
    quarter_start = date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)

    invoices = Invoice.objects.filter(workspace=workspace)

    def revenue_since(since: date) -> Decimal:
        # Accrual view: invoiced (open/paid) net revenue since a date.
        agg = invoices.filter(
            status__in=[InvoiceStatus.OPEN, InvoiceStatus.PAID, InvoiceStatus.OVERDUE],
            invoice_date__gte=since,
        ).aggregate(total=Sum("net_amount"))
        return money(agg["total"] or 0)

    open_receivables = money(
        invoices.filter(status__in=[InvoiceStatus.OPEN, InvoiceStatus.OVERDUE]).aggregate(
            total=Sum("open_amount")
        )["total"]
        or 0
    )
    overdue = money(
        invoices.filter(status=InvoiceStatus.OVERDUE).aggregate(total=Sum("open_amount"))["total"]
        or 0
    )
    draft_total = money(
        invoices.filter(
            status__in=[InvoiceStatus.DRAFT_LOCAL, InvoiceStatus.DRAFT_REMOTE]
        ).aggregate(total=Sum("gross_amount"))["total"]
        or 0
    )
    invoiced_total = money(
        invoices.filter(
            status__in=[InvoiceStatus.OPEN, InvoiceStatus.PAID, InvoiceStatus.OVERDUE],
            invoice_date__gte=year_start,
        ).aggregate(total=Sum("net_amount"))["total"]
        or 0
    )
    paid_total = money(
        invoices.filter(status=InvoiceStatus.PAID, invoice_date__gte=year_start).aggregate(
            total=Sum("gross_amount")
        )["total"]
        or 0
    )
    vat_invoiced_ytd = money(
        invoices.filter(
            status__in=[InvoiceStatus.OPEN, InvoiceStatus.PAID, InvoiceStatus.OVERDUE],
            invoice_date__gte=year_start,
        ).aggregate(total=Sum("tax_amount"))["total"]
        or 0
    )

    unbilled = TimeEntry.objects.filter(
        workspace=workspace,
        billable=True,
        billing_status=BillingStatus.OPEN,
        ended_at__isnull=False,
    ).aggregate(seconds=Sum("duration_seconds"), value=Sum("computed_amount"))

    return FinanceKPIs(
        revenue_ytd=revenue_since(year_start),
        revenue_month=revenue_since(month_start),
        revenue_quarter=revenue_since(quarter_start),
        open_receivables=open_receivables,
        overdue_receivables=overdue,
        draft_total=draft_total,
        unbilled_seconds=unbilled["seconds"] or 0,
        unbilled_value=money(unbilled["value"] or 0),
        invoiced_total=invoiced_total,
        paid_total=paid_total,
        vat_invoiced_ytd=vat_invoiced_ytd,
    )


FINALISED = [InvoiceStatus.OPEN, InvoiceStatus.OVERDUE, InvoiceStatus.PAID]


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, offset: int) -> date:
    month_index = value.year * 12 + (value.month - 1) + offset
    return date(month_index // 12, month_index % 12 + 1, 1)


def business_report(workspace: Any, today: date | None = None) -> dict[str, Any]:
    """The internal ERP view: every number the system knows, made comparable.

    One endpoint on purpose — the report page renders in a single request, and
    every figure here derives from the same base querysets so cards cannot
    contradict each other. All money leaves as strings (JSON floats round).
    """
    from django.db.models.functions import TruncMonth

    from apps.crm.models import Client
    from apps.projects.models import Project

    today = today or timezone.localdate()
    year_start = date(today.year, 1, 1)
    window_start = _shift_month(today, -11)  # 12 months incl. the current one
    last_90 = today - timedelta(days=90)

    invoices = Invoice.objects.filter(workspace=workspace)
    entries = TimeEntry.objects.filter(workspace=workspace, ended_at__isnull=False)
    kpis = compute_kpis(workspace, today)

    # ---- Monthly series -----------------------------------------------------
    invoiced_by_month = {
        row["month"].date() if hasattr(row["month"], "date") else row["month"]: row
        for row in invoices.filter(status__in=FINALISED, invoice_date__gte=window_start)
        .annotate(month=TruncMonth("invoice_date"))
        .values("month")
        .annotate(
            net=Sum("net_amount"), paid=Sum("net_amount", filter=Q(status=InvoiceStatus.PAID))
        )
    }
    hours_by_month = {
        row["month"].date() if hasattr(row["month"], "date") else row["month"]: row
        for row in entries.filter(started_at__date__gte=window_start)
        .annotate(month=TruncMonth("started_at"))
        .values("month")
        .annotate(
            seconds=Sum("duration_seconds"),
            billable_seconds=Sum("duration_seconds", filter=Q(billable=True), default=0),
        )
    }

    months = []
    for offset in range(-11, 1):
        month = _shift_month(today, offset)
        invoiced_row = invoiced_by_month.get(month, {})
        hours_row = hours_by_month.get(month, {})
        months.append(
            {
                "month": month.isoformat(),
                "invoiced_net": str(money(invoiced_row.get("net") or 0)),
                "paid_net": str(money(invoiced_row.get("paid") or 0)),
                "seconds": hours_row.get("seconds") or 0,
                "billable_seconds": hours_row.get("billable_seconds") or 0,
            }
        )

    # ---- Rates & behaviour --------------------------------------------------
    billed_ytd = entries.filter(
        billing_status=BillingStatus.BILLED, started_at__date__gte=year_start
    ).aggregate(seconds=Sum("duration_seconds"), value=Sum("computed_amount"))
    billed_seconds = billed_ytd["seconds"] or 0
    effective_rate = (
        money(Decimal(billed_ytd["value"] or 0) / (Decimal(billed_seconds) / Decimal(3600)))
        if billed_seconds
        else None
    )

    recent = entries.filter(started_at__date__gte=last_90).aggregate(
        seconds=Sum("duration_seconds"),
        billable=Sum("duration_seconds", filter=Q(billable=True), default=0),
    )
    billable_share = (
        round((recent["billable"] or 0) / recent["seconds"], 4) if recent["seconds"] else None
    )

    paid_recent = invoices.filter(
        status=InvoiceStatus.PAID,
        paid_at__isnull=False,
        invoice_date__isnull=False,
        invoice_date__gte=today - timedelta(days=365),
    ).values_list("invoice_date", "paid_at")
    pay_spans = [(paid - issued).days for issued, paid in paid_recent if paid >= issued]
    avg_days_to_pay = round(sum(pay_spans) / len(pay_spans), 1) if pay_spans else None

    active_client_ids = set(
        invoices.filter(status__in=FINALISED, invoice_date__gte=last_90).values_list(
            "client_id", flat=True
        )
    ) | set(entries.filter(started_at__date__gte=last_90).values_list("client_id", flat=True))

    # ---- Clients ------------------------------------------------------------
    revenue_ytd = kpis.invoiced_total
    client_rows = list(
        invoices.filter(status__in=FINALISED, invoice_date__gte=year_start)
        .values("client_id", "client__name")
        .annotate(
            net=Sum("net_amount"),
            open_gross=Sum(
                "open_amount",
                filter=Q(status__in=[InvoiceStatus.OPEN, InvoiceStatus.OVERDUE]),
                default=0,
            ),
        )
        .order_by("-net")
    )
    client_hours = {
        row["client_id"]: row
        for row in entries.filter(
            billing_status=BillingStatus.BILLED, started_at__date__gte=year_start
        )
        .values("client_id")
        .annotate(seconds=Sum("duration_seconds"))
    }
    clients = []
    for row in client_rows:
        seconds = (client_hours.get(row["client_id"], {}).get("seconds")) or 0
        net = money(row["net"] or 0)
        clients.append(
            {
                "id": str(row["client_id"]),
                "name": row["client__name"] or "—",
                "invoiced_net": str(net),
                "open_gross": str(money(row["open_gross"] or 0)),
                "seconds": seconds,
                "effective_rate": (
                    str(money(net / (Decimal(seconds) / Decimal(3600)))) if seconds else None
                ),
                "share": (round(float(net / revenue_ytd), 4) if revenue_ytd and net else 0.0),
            }
        )

    concentration = None
    if clients and revenue_ytd:
        top = clients[0]
        concentration = {"client_name": top["name"], "share": top["share"]}

    # ---- Services (billed work of the year, same base as revenue_breakdown) --
    services = [
        {
            "name": row["service_type__name"] or "Ohne Leistungsart",
            "value": str(money(row["value"] or 0)),
            "seconds": row["seconds"] or 0,
        }
        for row in entries.filter(
            billing_status=BillingStatus.BILLED, started_at__date__gte=year_start
        )
        .values("service_type__name")
        .annotate(value=Sum("computed_amount"), seconds=Sum("duration_seconds"))
        .order_by("-value")
    ]

    # ---- Project economics --------------------------------------------------
    project_time = {
        row["project_id"]: row
        for row in entries.filter(project__isnull=False)
        .values("project_id")
        .annotate(
            seconds=Sum("duration_seconds"),
            value=Sum("computed_amount", filter=Q(billable=True), default=0),
            unbilled_value=Sum(
                "computed_amount",
                filter=Q(
                    billable=True,
                    billing_status__in=[BillingStatus.OPEN, BillingStatus.MARKED],
                ),
                default=0,
            ),
        )
    }
    project_invoiced = {
        row["project_id"]: row["net"]
        for row in invoices.filter(status__in=FINALISED, project__isnull=False)
        .values("project_id")
        .annotate(net=Sum("net_amount"))
    }
    projects = []
    for project in Project.objects.filter(workspace=workspace, status="active").select_related(
        "client"
    ):
        time_row = project_time.get(project.pk, {})
        seconds = time_row.get("seconds") or 0
        budget_hours = Decimal(project.budget_hours) if project.budget_hours else None
        projects.append(
            {
                "id": str(project.pk),
                "name": project.name,
                "client_name": project.client.display_name,
                "seconds": seconds,
                "budget_hours": str(budget_hours) if budget_hours is not None else None,
                "budget_used_share": (
                    round(float(Decimal(seconds) / Decimal(3600) / budget_hours), 4)
                    if budget_hours
                    else None
                ),
                "value": str(money(time_row.get("value") or 0)),
                "unbilled_value": str(money(time_row.get("unbilled_value") or 0)),
                "invoiced_net": str(money(project_invoiced.get(project.pk) or 0)),
            }
        )
    projects.sort(key=lambda row: -row["seconds"])

    total_clients = Client.objects.filter(workspace=workspace).count()

    return {
        "year": today.year,
        "generated_at": timezone.now().isoformat(),
        "months": months,
        "kpis": {
            "revenue_ytd": str(kpis.revenue_ytd),
            "revenue_month": str(kpis.revenue_month),
            "revenue_quarter": str(kpis.revenue_quarter),
            "avg_monthly_revenue": str(
                money(
                    sum((Decimal(row["invoiced_net"]) for row in months), Decimal("0"))
                    / Decimal(max(1, sum(1 for row in months if Decimal(row["invoiced_net"]) > 0)))
                )
            ),
            "effective_hourly_rate": str(effective_rate) if effective_rate is not None else None,
            "billable_share_90d": billable_share,
            "avg_days_to_pay": avg_days_to_pay,
            "open_receivables": str(kpis.open_receivables),
            "overdue_receivables": str(kpis.overdue_receivables),
            "unbilled_value": str(kpis.unbilled_value),
            "unbilled_seconds": kpis.unbilled_seconds,
            "draft_total": str(kpis.draft_total),
            "active_clients_90d": len(active_client_ids),
            "total_clients": total_clients,
            "active_projects": len(projects),
        },
        "clients": clients,
        "services": services,
        "projects": projects,
        "concentration": concentration,
    }


def revenue_breakdown(workspace: Any, year: int) -> dict[str, list[dict[str, Any]]]:
    """Billed work by client and by service type — one source for both.

    Both cards deliberately aggregate the SAME base (billed time entries of
    the year) so they can never contradict each other. Earlier the client
    card used finalised invoices while the service card used billed entries —
    with only local drafts around, one showed data and the other "Keine
    Daten", which read as a bug (and was one). Invoice-based receivables live
    on the finance dashboard, where they belong.
    """
    year_start, year_end = _year_bounds(year)
    billed_entries = TimeEntry.objects.filter(
        workspace=workspace,
        billing_status=BillingStatus.BILLED,
        started_at__date__gte=year_start,
        started_at__date__lte=year_end,
    )

    by_client = (
        billed_entries.values("client__name")
        .annotate(total=Sum("computed_amount"))
        .order_by("-total")
    )
    by_service = (
        billed_entries.values("service_type__name")
        .annotate(total=Sum("computed_amount"))
        .order_by("-total")
    )

    return {
        "by_client": [
            {"label": row["client__name"] or "—", "value": str(money(row["total"] or 0))}
            for row in by_client
        ],
        "by_service": [
            {"label": row["service_type__name"] or "Ohne", "value": str(money(row["total"] or 0))}
            for row in by_service
        ],
    }


def get_ruleset(tax_year: int) -> TaxRuleSet | None:
    return (
        TaxRuleSet.objects.filter(tax_year=tax_year, enabled=True).order_by("-rule_version").first()
    )


def compute_reserve(
    workspace: Any,
    tax_year: int,
    *,
    scenario_annual_profit: Decimal | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Compute the recommended reserve for a year, with a full trace.

    If ``scenario_annual_profit`` is given, it overrides the projected profit —
    this powers the what-if scenarios (different rate, more/fewer hours, ±client).
    """
    today = today or timezone.localdate()
    ruleset = get_ruleset(tax_year)
    if ruleset is None:
        return {
            "available": False,
            "message": f"Keine Steuerregeln für {tax_year} hinterlegt.",
            "disclaimer": DISCLAIMER,
        }

    profile = TaxProfile.objects.filter(workspace=workspace, tax_year=tax_year).first()
    if profile is None:
        # Sensible defaults from the workspace so the page works before the user
        # fills in a profile.
        profile = TaxProfile(
            workspace=workspace,
            tax_year=tax_year,
            small_business=workspace.small_business,
        )

    kpis = compute_kpis(workspace, today)

    # Profit YTD (accrual): invoiced net revenue − expenses. Expenses are not yet
    # tracked locally (Lexware voucher sync, Phase 5+), so 0 for now — surfaced
    # honestly rather than invented.
    revenue_ytd = kpis.revenue_ytd + kpis.unbilled_value  # earned, incl. open work
    expenses_ytd = Decimal("0.00")
    profit_ytd = money(revenue_ytd - expenses_ytd)

    # Linear projection to year end based on elapsed fraction of the year.
    day_of_year = (today - date(today.year, 1, 1)).days + 1
    fraction = Decimal(day_of_year) / Decimal(366 if _is_leap(today.year) else 365)
    projected_profit = (
        scenario_annual_profit
        if scenario_annual_profit is not None
        else money(profit_ytd / fraction if fraction > 0 else profit_ytd)
    )

    church_rate = Decimal("8") if profile.federal_state in CHURCH_TAX_STATES_8 else Decimal("9")

    result = compute_taxes(
        annual_profit=projected_profit,
        config=ruleset.config,
        legal_form=profile.legal_form,
        small_business=profile.small_business,
        other_income=profile.other_taxable_income,
        joint_assessment=profile.joint_assessment,
        trade_tax_multiplier=profile.trade_tax_multiplier,
        church_tax=profile.church_tax,
        church_tax_rate=church_rate,
        annual_health_insurance=profile.estimated_monthly_health_insurance * 12,
        safety_margin_percent=profile.safety_margin_percent,
        vat_liability_ytd=kpis.vat_invoiced_ytd,
    )

    # The current reserve pot: the profile's opening balance plus every dated
    # booking on the ledger. Kept as a ledger (not one mutable number) so the
    # figure stays current and auditable without a bank connection — the
    # Lexware Public API exposes no account balances to sync from.
    transfer_row = ReserveTransfer.objects.filter(workspace=workspace).aggregate(
        total=Sum("amount"),
        last_date=Max("transfer_date"),
    )
    transfers_total = money(transfer_row["total"] or Decimal("0.00"))
    current_reserve = money(profile.existing_reserve + transfers_total)

    # Prepayments already made reduce the gap, not the recommendation.
    reserve_gap = money(result.recommended_reserve - current_reserve - profile.prepayments_made)

    return {
        "available": True,
        "tax_year": tax_year,
        "rule_version": ruleset.rule_version,
        "legal_form": profile.legal_form,
        "projected_annual_profit": str(projected_profit),
        "profit_ytd": str(profit_ytd),
        "revenue_ytd": str(revenue_ytd),
        "expenses_ytd": str(expenses_ytd),
        "income_tax": str(result.income_tax),
        "corporate_tax": str(result.corporate_tax),
        "soli": str(result.soli),
        "church_tax": str(result.church_tax),
        "trade_tax": str(result.trade_tax),
        "trade_tax_credit": str(result.trade_tax_credit),
        "vat_reserve": str(result.vat_reserve),
        "health_insurance": str(result.health_insurance),
        "safety_buffer": str(result.safety_buffer),
        "recommended_reserve": str(result.recommended_reserve),
        "existing_reserve": str(current_reserve),
        "reserve_opening": str(money(profile.existing_reserve)),
        "reserve_transfers_total": str(transfers_total),
        "last_transfer_date": (
            transfer_row["last_date"].isoformat() if transfer_row["last_date"] else None
        ),
        "prepayments_made": str(profile.prepayments_made),
        "reserve_gap": str(reserve_gap),
        "trace": result.trace_as_json(),
        "sources": ruleset.sources,
        "limitations": [
            (
                "Betriebsausgaben sind noch nicht angebunden; die Gewinn- und "
                "Steuerprognose ist deshalb konservativ und kann zu hoch ausfallen."
            ),
            (
                "Die Umsatzsteuer-Reserve enthält die Steuer aus finalisierten "
                "Ausgangsrechnungen, aber noch keine Vorsteuer oder bereits geleisteten "
                "USt-Vorauszahlungen."
            ),
            (
                "Nicht abgerechnete Zeiten fließen zum hinterlegten Stundensatz in die "
                "Gewinnprojektion ein, nicht jedoch in die Umsatzsteuer."
            ),
            (
                "Die Gesellschaftsrechnung umfasst Körperschaftsteuer, Soli und "
                "Gewerbesteuer; persönliche Steuern der Gesellschafter sind nicht enthalten."
                if profile.legal_form in ("ug", "gmbh")
                else (
                    "Persönliche Abzüge und die genaue steuerliche Behandlung von "
                    "Kranken-/Pflegeversicherungsbeiträgen sind nicht modelliert."
                )
            ),
        ],
        "disclaimer": DISCLAIMER,
    }


def _is_leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def create_snapshot(workspace: Any, today: date | None = None) -> ReserveSnapshot:
    """Persist a monthly reserve snapshot so a trend line is visible over time."""
    today = today or timezone.localdate()
    data = compute_reserve(workspace, today.year, today=today)
    if not data.get("available"):
        raise ValueError(data.get("message", "Rücklage nicht berechenbar."))

    ruleset = get_ruleset(today.year)
    snapshot, _ = ReserveSnapshot.objects.update_or_create(
        workspace=workspace,
        snapshot_date=today,
        defaults={
            "tax_year": today.year,
            "revenue_ytd": Decimal(data["revenue_ytd"]),
            "expenses_ytd": Decimal(data["expenses_ytd"]),
            "profit_ytd": Decimal(data["profit_ytd"]),
            "projected_annual_profit": Decimal(data["projected_annual_profit"]),
            "estimated_income_tax": Decimal(data["income_tax"]),
            "estimated_corporate_tax": Decimal(data["corporate_tax"]),
            "estimated_soli": Decimal(data["soli"]),
            "estimated_church_tax": Decimal(data["church_tax"]),
            "estimated_trade_tax": Decimal(data["trade_tax"]),
            "trade_tax_credit": Decimal(data["trade_tax_credit"]),
            "vat_reserve": Decimal(data["vat_reserve"]),
            "health_insurance_buffer": Decimal(data["health_insurance"]),
            "safety_buffer": Decimal(data["safety_buffer"]),
            "recommended_reserve": Decimal(data["recommended_reserve"]),
            "existing_reserve": Decimal(data["existing_reserve"]),
            "reserve_gap": Decimal(data["reserve_gap"]),
            "calculation_trace": {"trace": data["trace"]},
            "rule_set": ruleset,
        },
    )
    return snapshot
