import pytest

from hydro_agent.execution.registry import RuntimeRegistry


class Adapter:
    model_id = "fixture"
    capabilities = frozenset({"forecast"})


def test_registry():
    registry = RuntimeRegistry()
    adapter = Adapter()
    registry.register(adapter)
    assert registry.get("fixture", "forecast") is adapter
    with pytest.raises(ValueError, match="already registered"):
        registry.register(adapter)
    with pytest.raises(ValueError, match="does not support"):
        registry.get("fixture", "adapt")
    with pytest.raises(ValueError, match="unknown model"):
        registry.get("unknown", "forecast")
