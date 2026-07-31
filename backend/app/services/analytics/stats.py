"""Small statistical helpers.

Written out rather than pulled from numpy: the whole analytics engine is
dependency-free stdlib, which keeps the Docker image small and makes the maths
readable in review.
"""

from __future__ import annotations

from collections.abc import Sequence


def safe_div(numerator: float, denominator: float, *, default: float = 0.0) -> float:
    """Division that returns ``default`` instead of raising on an empty dataset."""
    return numerator / denominator if denominator else default


def mean(values: Sequence[float]) -> float:
    return safe_div(float(sum(values)), len(values))


def median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2


def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile (the same method numpy uses by default).

    ``pct`` is 0-100.
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])

    ordered = sorted(float(v) for v in values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def herfindahl(shares: Sequence[float]) -> float:
    """Concentration index over a set of shares that sum to 1.

    1.0 means a single supplier carries everything (maximum concentration
    risk); 1/n means perfectly even spread. Used to score dependency on any one
    vendor or country.
    """
    total = sum(shares)
    if total <= 0:
        return 0.0
    return sum((share / total) ** 2 for share in shares)


def round_to(value: float, digits: int = 2) -> float:
    return round(float(value), digits)
