from hydro_agent.optimization.contracts import CalibrationStrategy

XAJ_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="xaj-bounded-v1",
    max_candidates=32,
    random_seed=20260908,
    objective="nse",
    local_scale=None,
)

XAJ_PEAK_BIAS_V1 = CalibrationStrategy(
    strategy_id="xaj-peak-bias-v1",
    max_candidates=40,
    random_seed=20260911,
    objective="nse",
    local_scale=None,
)

XAJ_LOCAL_REFINE_V1 = CalibrationStrategy(
    strategy_id="xaj-local-refine-v1",
    max_candidates=24,
    random_seed=20260912,
    objective="nse",
    local_scale=0.25,
)


class CalibrationStrategyRegistry:
    def __init__(self) -> None:
        self._strategies = {
            s.strategy_id: s
            for s in (XAJ_BOUNDED_V1, XAJ_PEAK_BIAS_V1, XAJ_LOCAL_REFINE_V1)
        }

    def get(self, strategy_id: str) -> CalibrationStrategy:
        if strategy_id not in self._strategies:
            raise KeyError(strategy_id)
        return self._strategies[strategy_id]

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._strategies))
