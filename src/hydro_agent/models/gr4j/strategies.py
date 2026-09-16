"""GR4J strategies: model-scoped search contracts for the PDCA loop."""

from __future__ import annotations

from hydro_agent.optimization.contracts import CalibrationStrategy
from hydro_agent.optimization.strategies import MORRIS_SCREENING

GR4J_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="gr4j-bounded-v1",
    max_candidates=256,
    random_seed=20260316,
    objective="nse",
    local_scale=None,
    param_groups=("production", "exchange", "routing"),
    optimizer="dds",
    **MORRIS_SCREENING,
)

GR4J_ROUTING_REFINE_V1 = CalibrationStrategy(
    strategy_id="gr4j-routing-refine-v1",
    max_candidates=128,
    random_seed=20260317,
    objective="composite",
    local_scale=0.35,
    param_groups=("routing",),
    optimizer="sce-ua",
)

GR4J_PRODUCTION_REFINE_V1 = CalibrationStrategy(
    strategy_id="gr4j-production-refine-v1",
    max_candidates=128,
    random_seed=20260318,
    objective="composite",
    local_scale=0.35,
    param_groups=("production", "exchange"),
    optimizer="dds",
)

GR4J_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="gr4j-local-refine-v1",
    max_candidates=128,
    random_seed=20260319,
    objective="nse",
    local_scale=0.25,
    param_groups=("production", "exchange", "routing"),
    optimizer="dds",
)

GR4J_BROADENED_REFINE_V1 = CalibrationStrategy(
    strategy_id="gr4j-broadened-refine-v1",
    max_candidates=256,
    random_seed=20260320,
    objective="composite",
    local_scale=0.65,
    param_groups=("production", "exchange", "routing"),
    optimizer="dds",
)

GR4J_SCEUA_BENCHMARK_V1 = CalibrationStrategy(
    strategy_id="gr4j-sceua-benchmark-v1",
    max_candidates=256,
    random_seed=20260321,
    objective="nse",
    local_scale=None,
    param_groups=("production", "exchange", "routing"),
    optimizer="sce-ua",
)

GR4J_STRATEGIES = (
    GR4J_BOUNDED_V1,
    GR4J_ROUTING_REFINE_V1,
    GR4J_PRODUCTION_REFINE_V1,
    GR4J_LOCAL_REFINE_V1,
    GR4J_BROADENED_REFINE_V1,
    GR4J_SCEUA_BENCHMARK_V1,
)
