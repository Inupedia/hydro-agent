"""Tank-model strategies: model-scoped search contracts for the PDCA loop."""

from __future__ import annotations

from hydro_agent.optimization.contracts import CalibrationStrategy
from hydro_agent.optimization.strategies import MORRIS_SCREENING

TANK_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="tank-bounded-v1",
    max_candidates=256,
    random_seed=20260916,
    objective="nse",
    local_scale=None,
    param_groups=("surface", "intermediate", "base", "routing"),
    optimizer="dds",
    **MORRIS_SCREENING,
)

TANK_ROUTING_REFINE_V1 = CalibrationStrategy(
    strategy_id="tank-routing-refine-v1",
    max_candidates=128,
    random_seed=20260917,
    objective="composite",
    local_scale=0.35,
    param_groups=("routing",),
    optimizer="sce-ua",
)

TANK_PRODUCTION_REFINE_V1 = CalibrationStrategy(
    strategy_id="tank-production-refine-v1",
    max_candidates=128,
    random_seed=20260918,
    objective="composite",
    local_scale=0.35,
    param_groups=("surface", "intermediate", "base"),
    optimizer="dds",
)

TANK_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="tank-local-refine-v1",
    max_candidates=128,
    random_seed=20260919,
    objective="nse",
    local_scale=0.25,
    param_groups=("surface", "intermediate", "base", "routing"),
    optimizer="dds",
)

TANK_BROADENED_REFINE_V1 = CalibrationStrategy(
    strategy_id="tank-broadened-refine-v1",
    max_candidates=256,
    random_seed=20260920,
    objective="composite",
    local_scale=0.65,
    param_groups=("surface", "intermediate", "base", "routing"),
    optimizer="dds",
)

TANK_STRATEGIES = (
    TANK_BOUNDED_V1,
    TANK_ROUTING_REFINE_V1,
    TANK_PRODUCTION_REFINE_V1,
    TANK_LOCAL_REFINE_V1,
    TANK_BROADENED_REFINE_V1,
)
