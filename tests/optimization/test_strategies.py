import pytest

from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


def test_xaj_strategy_is_budgeted_and_unknown_strategy_fails():
    registry = CalibrationStrategyRegistry()
    strategy = registry.get("xaj-bounded-v1")
    assert strategy.max_candidates == 512
    assert strategy.random_seed == 20260908
    assert strategy.optimizer == "dds"
    assert registry.get("xaj-local-refine-v1").local_scale == 0.25
    assert registry.get("xaj-sceua-benchmark-v1").optimizer == "sce-ua"
    with pytest.raises(KeyError):
        registry.get("llm-made-up-search")
