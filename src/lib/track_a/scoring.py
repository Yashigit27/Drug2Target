from __future__ import annotations

import math


def safe_float(v: object, default: float = 0.0) -> float:
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def weighted_sum(parts: dict[str, float], weights: dict[str, float]) -> float:
    total_w = sum(max(0.0, float(w)) for w in weights.values())
    if total_w <= 0:
        return 0.0
    acc = 0.0
    for k, w in weights.items():
        acc += safe_float(parts.get(k, 0.0)) * max(0.0, float(w))
    return acc / total_w
