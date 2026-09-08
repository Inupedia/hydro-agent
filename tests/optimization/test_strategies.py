import pytest

from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


def test_xaj_strategy_is_frozen_and_unknown_strategy_fails():
    registry = CalibrationStrategyRegistry()
    strategy = registry.get("xaj-bounded-v1")
    assert strategy.max_candidates == 32
    assert strategy.random_seed == 20260908
    with pytest.raises(KeyError):
        registry.get("llm-made-up-search")
