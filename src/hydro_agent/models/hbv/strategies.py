"""HBV-light strategies: model-scoped search contracts for the PDCA loop."""

from __future__ import annotations

from hydro_agent.optimization.contracts import CalibrationStrategy
from hydro_agent.optimization.strategies import MORRIS_SCREENING

HBV_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="hbv-bounded-v1",
    max_candidates=256,
    random_seed=20260916,
    objective="nse",
    local_scale=None,
    param_groups=("snow", "soil", "groundwater", "routing"),
    optimizer="dds",
    **MORRIS_SCREENING,
)

HBV_ROUTING_REFINE_V1 = CalibrationStrategy(
    strategy_id="hbv-routing-refine-v1",
    max_candidates=128,
    random_seed=20260917,
    objective="composite",
    local_scale=0.35,
    param_groups=("routing",),
    optimizer="sce-ua",
)

HBV_WATER_BALANCE_REFINE_V1 = CalibrationStrategy(
    strategy_id="hbv-water-balance-refine-v1",
    max_candidates=128,
    random_seed=20260918,
    objective="composite",
    local_scale=0.35,
    param_groups=("snow", "soil", "groundwater"),
    optimizer="dds",
)

HBV_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="hbv-local-refine-v1",
    max_candidates=128,
    random_seed=20260919,
    objective="nse",
    local_scale=0.25,
    param_groups=("snow", "soil", "groundwater", "routing"),
    optimizer="dds",
)

HBV_BROADENED_REFINE_V1 = CalibrationStrategy(
    strategy_id="hbv-broadened-refine-v1",
    max_candidates=256,
    random_seed=20260920,
    objective="composite",
    local_scale=0.65,
    param_groups=("snow", "soil", "groundwater", "routing"),
    optimizer="dds",
)

HBV_STRATEGIES = (
    HBV_BOUNDED_V1,
    HBV_ROUTING_REFINE_V1,
    HBV_WATER_BALANCE_REFINE_V1,
    HBV_LOCAL_REFINE_V1,
    HBV_BROADENED_REFINE_V1,
)
