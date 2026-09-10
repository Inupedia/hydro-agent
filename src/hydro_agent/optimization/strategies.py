from hydro_agent.optimization.contracts import CalibrationStrategy

# Agent rounds are expensive reasoning steps; XAJ candidate evaluations are cheap CPU work.
# Give each hydrologist-selected experiment enough numerical depth to be meaningful.
XAJ_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="xaj-bounded-v1",
    max_candidates=256,
    random_seed=20260908,
    objective="nse",
    local_scale=None,
    param_groups=("evap", "runoff", "routing"),
)

XAJ_PEAK_BIAS_V1 = CalibrationStrategy(
    strategy_id="xaj-peak-bias-v1",
    max_candidates=320,
    random_seed=20260911,
    objective="composite",
    local_scale=None,
    param_groups=("runoff", "routing"),
)

XAJ_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="xaj-local-refine-v1",
    max_candidates=192,
    random_seed=20260912,
    objective="nse",
    local_scale=0.15,
    param_groups=("evap", "runoff", "routing"),
)

# Hydrologist notebook §6: parameters come from manual compare, not random search.
XAJ_HYDROLOGIST_MANUAL_V1 = CalibrationStrategy(
    strategy_id="xaj-hydrologist-manual-v1",
    max_candidates=1,
    random_seed=20260913,
    objective="nse",
    local_scale=None,
    param_groups=("evap", "runoff", "routing"),
)


class CalibrationStrategyRegistry:
    def __init__(self) -> None:
        self._strategies = {
            s.strategy_id: s
            for s in (
                XAJ_BOUNDED_V1,
                XAJ_PEAK_BIAS_V1,
                XAJ_LOCAL_REFINE_V1,
                XAJ_HYDROLOGIST_MANUAL_V1,
            )
        }

    def get(self, strategy_id: str) -> CalibrationStrategy:
        if strategy_id not in self._strategies:
            raise KeyError(strategy_id)
        return self._strategies[strategy_id]

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))
