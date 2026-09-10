import pytest

from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


def test_xaj_strategy_is_frozen_and_unknown_strategy_fails():
    registry = CalibrationStrategyRegistry()
    strategy = registry.get("xaj-bounded-v1")
    assert strategy.max_candidates == 256
    assert strategy.random_seed == 20260908
    assert registry.get("xaj-local-refine-v1").local_scale == 0.25
    with pytest.raises(KeyError):
        registry.get("llm-made-up-search")
