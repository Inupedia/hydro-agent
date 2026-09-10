from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal, Mapping

from hydro_agent.calibration.contracts import HydrologicGatePolicy

WaterBalanceTier = Literal["total", "annual", "seasonal", "pass"]


@dataclass(frozen=True)
class WaterBalanceProgress:
    """Lexicographic progress for P2 water-balance calibration.

    The rank encodes hydrologic priority rather than a weighted trade-off:

    3. total volume has not passed;
    2. total passed, annual balance has not;
    1. total + annual passed, seasonal balance has not;
    0. all three constraints passed.

    ``loss`` is a scalar projection used only by generic convergence/search code.
    Its disjoint [rank, rank + 1) bands preserve the lexicographic ordering, so a
    later-tier improvement can never compensate for regressing an already-passed
    upstream tier.
    """

    tier: WaterBalanceTier
    rank: int
    active_ratio: float
    loss: float
    total_ratio: float
    annual_ratio: float
    seasonal_ratio: float

    @property
    def passed(self) -> bool:
        return self.rank == 0


def _ratio(value: float, threshold: float) -> float:
    value = max(0.0, float(value))
    threshold = float(threshold)
    if threshold <= 0.0:
        return 0.0 if value <= 0.0 else float("inf")
    return value / threshold


def _bounded_ratio(value: float) -> float:
    """Map [0, +inf] to [0, 1) while keeping monotonic ordering."""

    value = max(0.0, float(value))
    if not isfinite(value):
        return 1.0
    return value / (1.0 + value)


def water_balance_progress(
    metrics: Mapping[str, float],
    policy: HydrologicGatePolicy,
) -> WaterBalanceProgress:
    total = _ratio(float(metrics.get("volume_rel_error", 0.0)), policy.water_balance_rel_error)
    annual = _ratio(
        float(metrics.get("annual_volume_bias_mae", 0.0)),
        policy.annual_water_balance_mae,
    )
    seasonal = _ratio(
        float(metrics.get("seasonal_volume_bias_mae", 0.0)),
        policy.seasonal_water_balance_mae,
    )

    if total > 1.0:
        tier: WaterBalanceTier = "total"
        rank = 3
        active = total
    elif annual > 1.0:
        tier = "annual"
        rank = 2
        active = annual
    elif seasonal > 1.0:
        tier = "seasonal"
        rank = 1
        active = seasonal
    else:
        tier = "pass"
        rank = 0
        active = max(total, annual, seasonal)

    return WaterBalanceProgress(
        tier=tier,
        rank=rank,
        active_ratio=active,
        loss=float(rank) + _bounded_ratio(active),
        total_ratio=total,
        annual_ratio=annual,
        seasonal_ratio=seasonal,
    )
