"""German tax calculation, driven entirely by a versioned TaxRuleSet.

The Einkommensteuer tariff (§32a EStG) is a piecewise polynomial; its
coefficients live in the ruleset ``config``, not in this code, so a new tax year
is a data edit. Every step is recorded in a trace so the forecast can show its
work — the brief's core requirement.

Nothing here is tax advice. See ``DISCLAIMER``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Any

from apps.core.money import money


def _d(value: Any) -> Decimal:
    return Decimal(str(value))


@dataclass
class TraceStep:
    label: str
    value: Decimal
    detail: str = ""


@dataclass
class TaxResult:
    income_tax: Decimal = Decimal("0.00")
    corporate_tax: Decimal = Decimal("0.00")
    soli: Decimal = Decimal("0.00")
    church_tax: Decimal = Decimal("0.00")
    trade_tax: Decimal = Decimal("0.00")
    trade_tax_credit: Decimal = Decimal("0.00")
    vat_reserve: Decimal = Decimal("0.00")
    health_insurance: Decimal = Decimal("0.00")
    safety_buffer: Decimal = Decimal("0.00")
    recommended_reserve: Decimal = Decimal("0.00")
    trace: list[TraceStep] = field(default_factory=list)

    def add(self, label: str, value: Decimal, detail: str = "") -> None:
        self.trace.append(TraceStep(label=label, value=money(value), detail=detail))

    def trace_as_json(self) -> list[dict[str, Any]]:
        return [
            {"label": step.label, "value": str(step.value), "detail": step.detail}
            for step in self.trace
        ]


def income_tax_tariff(zve: Decimal, config: dict[str, Any]) -> Decimal:
    """Compute Einkommensteuer for a taxable income using the ruleset's zones.

    ``config['income_tax_zones']`` is a list of zone dicts, each with an upper
    bound and the polynomial coefficients for that zone (§32a EStG form).
    """
    zones = config["income_tax_zones"]
    # §32a EStG floors both the taxable income and the resulting tariff tax to
    # full euros.  Commercial rounding can cross a tariff boundary.
    zve = max(zve, Decimal("0")).quantize(Decimal("1"), rounding=ROUND_DOWN)
    for zone in zones:
        upper = zone.get("up_to")
        if upper is None or zve <= _d(upper):
            kind = zone["type"]
            if kind == "zero":
                return Decimal("0")
            if kind == "progressive":
                # tax = (a * y + b) * y + c, with y = (zve - base) / 10000
                y = (zve - _d(zone["base"])) / _d(10000)
                a, b, c = _d(zone["a"]), _d(zone["b"]), _d(zone["c"])
                return ((a * y + b) * y + c).quantize(Decimal("1"), rounding=ROUND_DOWN)
            if kind == "linear":
                # tax = rate * zve - subtract
                return (_d(zone["rate"]) * zve - _d(zone["subtract"])).quantize(
                    Decimal("1"), rounding=ROUND_DOWN
                )
    # Fallback: top linear zone.
    top = zones[-1]
    return (_d(top["rate"]) * zve - _d(top["subtract"])).quantize(Decimal("1"), rounding=ROUND_DOWN)


def compute_taxes(
    *,
    annual_profit: Decimal,
    config: dict[str, Any],
    legal_form: str,
    small_business: bool,
    other_income: Decimal,
    joint_assessment: bool,
    trade_tax_multiplier: int,
    church_tax: bool,
    church_tax_rate: Decimal,
    annual_health_insurance: Decimal,
    safety_margin_percent: Decimal,
    vat_liability_ytd: Decimal,
) -> TaxResult:
    """Full reserve computation with a step-by-step trace."""
    result = TaxResult()

    is_corporation = legal_form in ("ug", "gmbh")
    if is_corporation:
        corporate_tax = (
            max(annual_profit, Decimal("0")) * _d(config["corporate_tax_rate"]) / Decimal("100")
        )
        result.corporate_tax = money(corporate_tax)
        result.add(
            "Körperschaftsteuer",
            result.corporate_tax,
            f"{config['corporate_tax_rate']}% des prognostizierten Unternehmensgewinns (§23 KStG)",
        )
    else:
        taxable_income = annual_profit + other_income
        result.add(
            "Zu versteuerndes Einkommen (Basis)",
            taxable_income,
            "Prognostizierter Jahresgewinn + weitere Einkünfte; vor persönlichen Abzügen",
        )

        # Splitting: halve the base, tax it, double the result (approximation).
        if joint_assessment:
            half = taxable_income / 2
            tax = income_tax_tariff(half, config) * 2
            result.add(
                "Einkommensteuer (Splitting)",
                tax,
                "Splittingverfahren: Tarif auf halbes zvE, verdoppelt",
            )
        else:
            tax = income_tax_tariff(taxable_income, config)
            result.add("Einkommensteuer (Grundtarif)", tax, "§32a EStG")
        result.income_tax = money(max(tax, Decimal("0")))

    # Gewerbesteuer — only for trade businesses, not Freiberufler.
    if legal_form in ("sole", "ug", "gmbh") and legal_form != "freelancer":
        # §11 GewStG first floors the Gewerbeertrag to full hundreds.  The
        # 24,500 € allowance applies to natural persons/partnerships, never to
        # corporations such as UG/GmbH.
        rounded_profit = max(annual_profit, Decimal("0")).quantize(
            Decimal("1E2"), rounding=ROUND_DOWN
        )
        allowance = _d(config["trade_tax_allowance"]) if legal_form == "sole" else Decimal("0")
        base_amount = _d(config["trade_tax_base_rate"])  # Steuermesszahl 3.5%
        trade_base = max(rounded_profit - allowance, Decimal("0"))
        messbetrag = trade_base * base_amount / Decimal("100")
        trade_tax = messbetrag * _d(trade_tax_multiplier) / Decimal("100")
        result.trade_tax = money(trade_tax)
        result.add(
            "Gewerbesteuer",
            result.trade_tax,
            f"({rounded_profit:.0f} − {allowance:.0f} Freibetrag) × {base_amount}% × "
            f"{trade_tax_multiplier}% Hebesatz",
        )
        # §35 EStG credit: 4 × Messbetrag, also capped by the income-tax share
        # attributable to positive business income and by actual trade tax.
        if legal_form == "sole":
            credit_factor = _d(config["trade_tax_credit_factor"])
            business_income = max(annual_profit, Decimal("0"))
            positive_income = business_income + max(other_income, Decimal("0"))
            attributable_income_tax = (
                result.income_tax * business_income / positive_income
                if positive_income > 0
                else Decimal("0")
            )
            credit = min(
                messbetrag * credit_factor,
                attributable_income_tax,
                result.trade_tax,
            )
            result.trade_tax_credit = money(credit)
            result.add(
                "Gewerbesteueranrechnung (§35 EStG)",
                -result.trade_tax_credit,
                f"{credit_factor.normalize()} × Messbetrag; gedeckelt auf anteilige ESt und "
                "Gewerbesteuer",
            )

    # Soli: corporations pay 5.5% of corporation tax.  For individuals the
    # statutory 11.9% phase-in cap prevents the jump directly above the limit.
    soli_base = result.corporate_tax if is_corporation else result.income_tax
    soli_threshold = Decimal("0") if is_corporation else _d(config["soli_free_limit"])
    if joint_assessment and not is_corporation:
        soli_threshold *= 2
    if soli_base > soli_threshold:
        full_soli = soli_base * _d(config["soli_rate"]) / Decimal("100")
        soli = (
            full_soli
            if is_corporation
            else min(full_soli, (soli_base - soli_threshold) * Decimal("0.119"))
        )
        result.soli = money(soli)
        result.add(
            "Solidaritätszuschlag",
            result.soli,
            (
                f"{config['soli_rate']}% der Körperschaftsteuer"
                if is_corporation
                else f"max. 11,9% des Betrags über {soli_threshold} €; gedeckelt auf "
                f"{config['soli_rate']}% der ESt"
            ),
        )
    else:
        result.add("Solidaritätszuschlag", Decimal("0"), f"ESt unter Freigrenze {soli_threshold} €")

    # Kirchensteuer: % of income tax.
    if church_tax and not is_corporation:
        kt = result.income_tax * church_tax_rate / Decimal("100")
        result.church_tax = money(kt)
        result.add("Kirchensteuer", result.church_tax, f"{church_tax_rate}% der ESt")

    # Reserve the tax actually present on final invoices.  Applying 19% to all
    # earned/unbilled work was wrong for reduced/zero-rated lines and work that
    # has not been invoiced yet. Input VAT/prepayments remain an explicit model
    # limitation handled by the caller.
    if not small_business:
        result.vat_reserve = money(max(vat_liability_ytd, Decimal("0")))
        result.add(
            "Umsatzsteuer-Reserve",
            result.vat_reserve,
            "Umsatzsteuer aus finalisierten Ausgangsrechnungen",
        )
    else:
        result.add("Umsatzsteuer-Reserve", Decimal("0"), "Kleinunternehmer §19 UStG")

    if not is_corporation:
        result.health_insurance = money(annual_health_insurance)
        result.add(
            "Kranken-/Pflegeversicherung",
            result.health_insurance,
            "Geschätzter Jahresbeitrag; steuerliche Abzugsfähigkeit nicht modelliert",
        )

    # Recommended reserve = taxes net of credits + prepayments handled by caller,
    # + VAT + health insurance + safety margin.
    tax_burden = (
        result.income_tax
        + result.corporate_tax
        + result.soli
        + result.church_tax
        + result.trade_tax
        - result.trade_tax_credit
    )
    subtotal = tax_burden + result.vat_reserve + result.health_insurance
    safety = subtotal * safety_margin_percent / Decimal("100")
    result.safety_buffer = money(safety)
    result.add(
        "Sicherheitsaufschlag", result.safety_buffer, f"{safety_margin_percent}% auf Zwischensumme"
    )

    result.recommended_reserve = money(subtotal + safety)
    result.add("Empfohlene Gesamtrücklage", result.recommended_reserve, "")
    return result
