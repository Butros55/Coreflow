"""Money and duration arithmetic.

Every monetary value in Coreflow is a ``Decimal`` quantised to two places with
``ROUND_HALF_UP`` (the convention German invoices use). Floats are never used for
money — binary floating point cannot represent 0.10 exactly, and the error
compounds across invoice lines.

Hours are quantised to four places before being multiplied by a rate, so that a
37-second entry does not silently become 0.00 h.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Final

MONEY_PLACES: Final = Decimal("0.01")
HOUR_PLACES: Final = Decimal("0.0001")
RATE_PLACES: Final = Decimal("0.01")
PERCENT_PLACES: Final = Decimal("0.0001")

ZERO: Final = Decimal("0.00")
SECONDS_PER_HOUR: Final = Decimal(3600)


def money(value: Decimal | int | str) -> Decimal:
    """Quantise a value to a 2-place monetary Decimal, rounding half up."""
    return Decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def hours(value: Decimal | int | str) -> Decimal:
    """Quantise a value to a 4-place hours Decimal."""
    return Decimal(value).quantize(HOUR_PLACES, rounding=ROUND_HALF_UP)


def rate(value: Decimal | int | str) -> Decimal:
    """Quantise an hourly rate to 2 places."""
    return Decimal(value).quantize(RATE_PLACES, rounding=ROUND_HALF_UP)


def seconds_to_hours(seconds: int) -> Decimal:
    """Convert a duration in seconds to a 4-place Decimal of hours."""
    return hours(Decimal(seconds) / SECONDS_PER_HOUR)


def hours_to_seconds(value: Decimal) -> int:
    """Convert Decimal hours back to whole seconds."""
    return int((Decimal(value) * SECONDS_PER_HOUR).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_amount(duration_seconds: int, hourly_rate: Decimal) -> Decimal:
    """Compute the billable amount for a duration at a given rate.

    Rounds once, at the end: quantising the hours first and the product second
    would double-round and drift by a cent on long entries.
    """
    exact = (Decimal(duration_seconds) / SECONDS_PER_HOUR) * Decimal(hourly_rate)
    return money(exact)


def apply_percent(base: Decimal, percent: Decimal) -> Decimal:
    """Apply a percentage (e.g. Decimal('19') for 19%) to a monetary base."""
    return money(Decimal(base) * Decimal(percent) / Decimal(100))


def sum_money(values: list[Decimal]) -> Decimal:
    """Sum monetary values, keeping the result quantised."""
    total = sum(values, ZERO)
    return money(total)
