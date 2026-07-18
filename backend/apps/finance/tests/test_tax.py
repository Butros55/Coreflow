"""Tax tariff and reserve calculation.

The income-tax numbers are checked against the known §32a EStG 2025 tariff. If
these drift, the forecast is silently wrong — exactly the failure the versioned,
sourced ruleset exists to prevent.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.finance.rulesets import DEFAULT_RULESETS
from apps.finance.tax import TaxResult, compute_taxes, income_tax_tariff

# The 2025 ruleset config, used directly for tariff assertions.
CONFIG_2025 = next(r for r in DEFAULT_RULESETS if r["tax_year"] == 2025)["config"]

pytestmark = pytest.mark.django_db


class TestIncomeTaxTariff:
    def test_below_grundfreibetrag_is_zero(self) -> None:
        assert income_tax_tariff(Decimal("12000"), CONFIG_2025) == Decimal("0")
        assert income_tax_tariff(Decimal("12096"), CONFIG_2025) == Decimal("0")

    @pytest.mark.parametrize(
        ("zve", "expected"),
        [
            # Official §32a EStG 2025 Grundtarif outputs (whole euros).
            (15000, 485),
            (30000, 4304),
            (50000, 10691),
            (70000, 18488),
            (100000, 31088),
            (300000, 115753),
        ],
    )
    def test_known_reference_points(self, zve: int, expected: int) -> None:
        tax = income_tax_tariff(Decimal(zve), CONFIG_2025)
        # Within one euro of the published tariff (rounding of the last cent).
        assert abs(tax - Decimal(expected)) <= Decimal("1"), (
            f"zvE {zve}: got {tax}, expected {expected}"
        )

    def test_top_rate_is_45_percent_marginal(self) -> None:
        low = income_tax_tariff(Decimal("300000"), CONFIG_2025)
        high = income_tax_tariff(Decimal("400000"), CONFIG_2025)
        marginal = (high - low) / Decimal("100000")
        assert abs(marginal - Decimal("0.45")) < Decimal("0.001")


class TestComputeTaxes:
    def _compute(self, **overrides: object) -> TaxResult:
        defaults: dict[str, object] = {
            "annual_profit": Decimal("60000"),
            "config": CONFIG_2025,
            "legal_form": "sole",
            "small_business": False,
            "other_income": Decimal("0"),
            "joint_assessment": False,
            "trade_tax_multiplier": 400,
            "church_tax": False,
            "church_tax_rate": Decimal("8"),
            "annual_health_insurance": Decimal("6000"),
            "safety_margin_percent": Decimal("5"),
            "revenue_ytd": Decimal("60000"),
        }
        defaults.update(overrides)
        return compute_taxes(**defaults)  # type: ignore[arg-type]

    def test_produces_a_full_trace(self) -> None:
        result = self._compute()
        labels = [step.label for step in result.trace]
        assert "Einkommensteuer (Grundtarif)" in labels
        assert "Empfohlene Gesamtrücklage" in labels
        # The trace ends with the recommendation.
        assert result.trace[-1].value == result.recommended_reserve

    def test_small_business_has_no_vat_reserve(self) -> None:
        result = self._compute(small_business=True)
        assert result.vat_reserve == Decimal("0.00")

    def test_non_small_business_reserves_vat(self) -> None:
        result = self._compute(small_business=False, revenue_ytd=Decimal("100000"))
        # 19% of 100k net revenue.
        assert result.vat_reserve == Decimal("19000.00")

    def test_freelancer_has_no_trade_tax(self) -> None:
        result = self._compute(legal_form="freelancer")
        assert result.trade_tax == Decimal("0.00")

    def test_sole_trader_has_trade_tax_and_credit(self) -> None:
        result = self._compute(legal_form="sole", annual_profit=Decimal("60000"))
        assert result.trade_tax > Decimal("0")
        # §35 credit reduces the burden.
        assert result.trade_tax_credit > Decimal("0")

    def test_church_tax_applied_when_enabled(self) -> None:
        without = self._compute(church_tax=False)
        with_church = self._compute(church_tax=True, church_tax_rate=Decimal("8"))
        assert with_church.church_tax > Decimal("0")
        assert without.church_tax == Decimal("0.00")
        # 8% of income tax.
        expected = (with_church.income_tax * Decimal("8") / Decimal("100")).quantize(
            Decimal("0.01")
        )
        assert with_church.church_tax == expected

    def test_soli_only_above_threshold(self) -> None:
        # Small profit → income tax below the Soli Freigrenze → no Soli.
        small = self._compute(annual_profit=Decimal("25000"))
        assert small.soli == Decimal("0.00")
        # Large profit → Soli applies.
        large = self._compute(annual_profit=Decimal("200000"))
        assert large.soli > Decimal("0")

    def test_safety_margin_increases_reserve(self) -> None:
        low = self._compute(safety_margin_percent=Decimal("0"))
        high = self._compute(safety_margin_percent=Decimal("20"))
        assert high.recommended_reserve > low.recommended_reserve

    def test_recommendation_is_sum_of_components(self) -> None:
        result = self._compute()
        expected = (
            result.income_tax
            + result.soli
            + result.church_tax
            + result.trade_tax
            - result.trade_tax_credit
            + result.vat_reserve
            + result.health_insurance
            + result.safety_buffer
        )
        assert result.recommended_reserve == expected.quantize(Decimal("0.01"))
