from hydro_agent.optimization.contracts import CalibrationStrategy

# Research strategies: the Agent chooses WHAT/WHY; a deterministic numerical
# optimizer searches concrete values under teacher/kernel bounds. DDS is the
# default for higher-dimensional/budget-limited searches; SCE-UA is retained for
# low-dimensional refinement and benchmark/ablation runs.
XAJ_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="xaj-bounded-v1",
    max_candidates=512,
    random_seed=20260908,
    objective="nse",
    local_scale=None,
    param_groups=("evap", "runoff", "routing"),
    optimizer="dds",
)

XAJ_PEAK_BIAS_V1 = CalibrationStrategy(
    strategy_id="xaj-peak-bias-v1",
    max_candidates=384,
    random_seed=20260911,
    objective="composite",
    local_scale=None,
    param_groups=("runoff", "routing"),
    optimizer="dds",
)

XAJ_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="xaj-local-refine-v1",
    max_candidates=256,
    random_seed=20260912,
    objective="nse",
    local_scale=0.25,
    param_groups=("evap", "runoff", "routing"),
    optimizer="dds",
)

# Process-oriented strategies used by the calibration-scientist loop.
XAJ_WATER_BALANCE_V1 = CalibrationStrategy(
    strategy_id="xaj-water-balance-v1",
    max_candidates=384,
    random_seed=20260914,
    objective="composite",
    local_scale=0.35,
    param_groups=("evap", "runoff"),
    optimizer="dds",
)

# Routing is only four parameters, so the classic SCE-UA benchmark remains a
# sensible default here and gives the scientist two genuinely different search
# mechanisms rather than cosmetic strategy rotation.
XAJ_ROUTING_REFINE_V1 = CalibrationStrategy(
    strategy_id="xaj-routing-refine-v1",
    max_candidates=256,
    random_seed=20260915,
    objective="composite",
    local_scale=0.35,
    param_groups=("routing",),
    optimizer="sce-ua",
)

XAJ_HYDRO_COMPOSITE_V1 = CalibrationStrategy(
    strategy_id="xaj-hydro-composite-v1",
    max_candidates=512,
    random_seed=20260916,
    objective="composite",
    local_scale=0.35,
    param_groups=("evap", "runoff", "routing"),
    optimizer="dds",
)

# Second-stage search used only when the selected candidate presses against a
# local search window while the teacher/kernel absolute range still has room.
# It never expands beyond the absolute parameter bounds.
XAJ_BROADENED_REFINE_V1 = CalibrationStrategy(
    strategy_id="xaj-broadened-refine-v1",
    max_candidates=512,
    random_seed=20260917,
    objective="composite",
    local_scale=0.65,
    param_groups=("evap", "runoff", "routing"),
    optimizer="dds",
)

# Explicit SCE-UA full-search benchmark for O/P/A experiments. Keeping this as
# a first-class strategy lets evaluation compare Agent value at the same budget.
XAJ_SCEUA_BENCHMARK_V1 = CalibrationStrategy(
    strategy_id="xaj-sceua-benchmark-v1",
    max_candidates=512,
    random_seed=20260918,
    objective="nse",
    local_scale=None,
    param_groups=("evap", "runoff", "routing"),
    optimizer="sce-ua",
)

# Explicit random baseline retained for ablation and fair O/P/A experiments.
XAJ_RANDOM_SEARCH_V1 = CalibrationStrategy(
    strategy_id="xaj-random-search-v1",
    max_candidates=128,
    random_seed=20260908,
    objective="nse",
    local_scale=None,
    param_groups=("evap", "runoff", "routing"),
    optimizer="random-search",
)

# Hydrologist notebook §6: parameters come from manual compare, not numerical search.
XAJ_HYDROLOGIST_MANUAL_V1 = CalibrationStrategy(
    strategy_id="xaj-hydrologist-manual-v1",
    max_candidates=1,
    random_seed=20260913,
    objective="nse",
    local_scale=None,
    param_groups=("evap", "runoff", "routing"),
    optimizer="manual",
)


class CalibrationStrategyRegistry:
    def __init__(self) -> None:
        self._strategies = {
            s.strategy_id: s
            for s in (
                XAJ_BOUNDED_V1,
                XAJ_PEAK_BIAS_V1,
                XAJ_LOCAL_REFINE_V1,
                XAJ_WATER_BALANCE_V1,
                XAJ_ROUTING_REFINE_V1,
                XAJ_HYDRO_COMPOSITE_V1,
                XAJ_BROADENED_REFINE_V1,
                XAJ_SCEUA_BENCHMARK_V1,
                XAJ_RANDOM_SEARCH_V1,
                XAJ_HYDROLOGIST_MANUAL_V1,
            )
        }

    def get(self, strategy_id: str) -> CalibrationStrategy:
        if strategy_id not in self._strategies:
            raise KeyError(strategy_id)
        return self._strategies[strategy_id]

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))
