"""Finance aggregation: KPIs, cashflow vs accrual, and the reserve forecast."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.utils import timezone

from apps.core.money import money
from apps.finance.models import DISCLAIMER, ReserveSnapshot, TaxProfile, TaxRuleSet
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
    )


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
        revenue_ytd=revenue_ytd,
    )

    # Prepayments already made reduce the gap, not the recommendation.
    reserve_gap = money(
        result.recommended_reserve - profile.existing_reserve - profile.prepayments_made
    )

    return {
        "available": True,
        "tax_year": tax_year,
        "rule_version": ruleset.rule_version,
        "projected_annual_profit": str(projected_profit),
        "profit_ytd": str(profit_ytd),
        "revenue_ytd": str(revenue_ytd),
        "expenses_ytd": str(expenses_ytd),
        "income_tax": str(result.income_tax),
        "soli": str(result.soli),
        "church_tax": str(result.church_tax),
        "trade_tax": str(result.trade_tax),
        "trade_tax_credit": str(result.trade_tax_credit),
        "vat_reserve": str(result.vat_reserve),
        "health_insurance": str(result.health_insurance),
        "safety_buffer": str(result.safety_buffer),
        "recommended_reserve": str(result.recommended_reserve),
        "existing_reserve": str(profile.existing_reserve),
        "prepayments_made": str(profile.prepayments_made),
        "reserve_gap": str(reserve_gap),
        "trace": result.trace_as_json(),
        "sources": ruleset.sources,
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
