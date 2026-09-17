"""SAC-SMA strategies: model-scoped search contracts for the PDCA loop."""

from __future__ import annotations

from hydro_agent.optimization.contracts import CalibrationStrategy
from hydro_agent.optimization.strategies import MORRIS_SCREENING

SAC_SMA_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="sac-sma-bounded-v1",
    max_candidates=256,
    random_seed=20260916,
    objective="nse",
    local_scale=None,
    param_groups=("upper", "lower", "percolation", "routing"),
    optimizer="dds",
    **MORRIS_SCREENING,
)

SAC_SMA_ROUTING_REFINE_V1 = CalibrationStrategy(
    strategy_id="sac-sma-routing-refine-v1",
    max_candidates=128,
    random_seed=20260917,
    objective="composite",
    local_scale=0.35,
    param_groups=("routing",),
    optimizer="sce-ua",
)

SAC_SMA_WATER_BALANCE_REFINE_V1 = CalibrationStrategy(
    strategy_id="sac-sma-water-balance-refine-v1",
    max_candidates=128,
    random_seed=20260918,
    objective="composite",
    local_scale=0.35,
    param_groups=("upper", "lower", "percolation"),
    optimizer="dds",
)

SAC_SMA_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="sac-sma-local-refine-v1",
    max_candidates=128,
    random_seed=20260919,
    objective="nse",
    local_scale=0.25,
    param_groups=("upper", "lower", "percolation", "routing"),
    optimizer="dds",
)

SAC_SMA_BROADENED_REFINE_V1 = CalibrationStrategy(
    strategy_id="sac-sma-broadened-refine-v1",
    max_candidates=256,
    random_seed=20260920,
    objective="composite",
    local_scale=0.65,
    param_groups=("upper", "lower", "percolation", "routing"),
    optimizer="dds",
)

SAC_SMA_STRATEGIES = (
    SAC_SMA_BOUNDED_V1,
    SAC_SMA_ROUTING_REFINE_V1,
    SAC_SMA_WATER_BALANCE_REFINE_V1,
    SAC_SMA_LOCAL_REFINE_V1,
    SAC_SMA_BROADENED_REFINE_V1,
)
