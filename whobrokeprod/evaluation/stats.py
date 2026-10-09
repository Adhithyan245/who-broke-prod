"""Stdlib statistics: Wilson interval and exact two-sided sign test."""
from __future__ import annotations

from math import comb, sqrt


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, mid - half), min(1.0, mid + half))


def sign_test(a: list[int], b: list[int]) -> tuple[int, int, float]:
    """Paired binary outcomes. Returns (#a-only wins, #b-only wins, two-sided exact p)."""
    pos = sum(1 for x, y in zip(a, b) if x > y)
    neg = sum(1 for x, y in zip(a, b) if x < y)
    n = pos + neg
    if n == 0:
        return pos, neg, 1.0
    k = min(pos, neg)
    p = 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n
    return pos, neg, min(1.0, p)
