"""Money and duration arithmetic.

These tests exist because float money bugs are silent: they produce plausible
numbers that are one cent wrong, and nobody notices until a tax audit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from apps.core.money import (
    apply_percent,
    hours,
    hours_to_seconds,
    line_amount,
    money,
    seconds_to_hours,
    sum_money,
)


class TestMoney:
    def test_quantises_to_two_places(self) -> None:
        assert money(Decimal("10.005")) == Decimal("10.01")
        assert money(Decimal("10.004")) == Decimal("10.00")

    def test_rounds_half_up_not_bankers(self) -> None:
        """Python's default is banker's rounding, which German invoices don't use.

        Decimal('0.5') would round to 0 under ROUND_HALF_EVEN. Invoices expect 1.
        """
        assert money(Decimal("0.005")) == Decimal("0.01")
        assert money(Decimal("0.015")) == Decimal("0.02")
        assert money(Decimal("0.025")) == Decimal("0.03")

    def test_accepts_string_input_without_float_contamination(self) -> None:
        # Decimal(0.1) from a float is 0.1000000000000000055511151231257827…
        # Going through str keeps it exact.
        assert money("0.1") == Decimal("0.10")

    def test_sum_money_stays_exact(self) -> None:
        values = [Decimal("0.10")] * 10
        assert sum_money(values) == Decimal("1.00")

    def test_decimal_avoids_the_float_representation_error(self) -> None:
        """The reason money is Decimal, pinned as an executable statement."""
        assert 0.1 + 0.2 != 0.3  # float
        assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")  # Decimal
        assert money(Decimal("0.1") + Decimal("0.2")) == Decimal("0.30")


class TestHours:
    def test_seconds_to_hours(self) -> None:
        assert seconds_to_hours(3600) == Decimal("1.0000")
        assert seconds_to_hours(1800) == Decimal("0.5000")
        assert seconds_to_hours(0) == Decimal("0.0000")

    def test_short_entries_do_not_collapse_to_zero(self) -> None:
        """A 37-second entry must survive as a non-zero duration."""
        assert seconds_to_hours(37) == Decimal("0.0103")
        assert seconds_to_hours(37) > 0

    def test_round_trip_is_stable_for_whole_minutes(self) -> None:
        for seconds in (60, 300, 900, 3600, 7200, 27000):
            assert hours_to_seconds(seconds_to_hours(seconds)) == seconds

    def test_hours_quantises_to_four_places(self) -> None:
        assert hours(Decimal("1.00005")) == Decimal("1.0001")


class TestLineAmount:
    def test_simple_case(self) -> None:
        assert line_amount(3600, Decimal("95.00")) == Decimal("95.00")
        assert line_amount(1800, Decimal("95.00")) == Decimal("47.50")

    def test_rounds_once_at_the_end(self) -> None:
        """Quantising hours first and multiplying second double-rounds.

        7280s = 2.0222… h. Rounding to 2.0222 h then multiplying by 95 gives
        192.109, i.e. 192.11. Multiplying exactly gives 192.1111… → 192.11.
        They agree here, but the single-round path is the one that stays correct
        as rates and durations grow; this test pins the behaviour.
        """
        assert line_amount(7280, Decimal("95.00")) == Decimal("192.11")

    def test_long_duration_high_rate(self) -> None:
        # 100 hours at 187.50
        assert line_amount(360000, Decimal("187.50")) == Decimal("18750.00")

    def test_zero_duration(self) -> None:
        assert line_amount(0, Decimal("95.00")) == Decimal("0.00")

    @pytest.mark.parametrize(
        ("seconds", "rate", "expected"),
        [
            (2700, "80.00", "60.00"),  # 45 min
            (5400, "120.00", "180.00"),  # 90 min
            (1, "95.00", "0.03"),  # 1 second
            (59, "95.00", "1.56"),  # 59 seconds
        ],
    )
    def test_cases(self, seconds: int, rate: str, expected: str) -> None:
        assert line_amount(seconds, Decimal(rate)) == Decimal(expected)


class TestApplyPercent:
    def test_german_vat_rates(self) -> None:
        assert apply_percent(Decimal("100.00"), Decimal("19")) == Decimal("19.00")
        assert apply_percent(Decimal("100.00"), Decimal("7")) == Decimal("7.00")
        assert apply_percent(Decimal("100.00"), Decimal("0")) == Decimal("0.00")

    def test_awkward_base(self) -> None:
        # 19% of 13.40 = 2.546 → 2.55
        assert apply_percent(Decimal("13.40"), Decimal("19")) == Decimal("2.55")
