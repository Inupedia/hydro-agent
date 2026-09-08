from hydro_agent.optimization.contracts import CalibrationStrategy

XAJ_BOUNDED_V1 = CalibrationStrategy(
    strategy_id="xaj-bounded-v1",
    max_candidates=32,
    random_seed=20260908,
    objective="nse",
)


class CalibrationStrategyRegistry:
    def __init__(self) -> None:
        self._strategies = {XAJ_BOUNDED_V1.strategy_id: XAJ_BOUNDED_V1}

    def get(self, strategy_id: str) -> CalibrationStrategy:
        if strategy_id not in self._strategies:
            raise KeyError(strategy_id)
        return self._strategies[strategy_id]
