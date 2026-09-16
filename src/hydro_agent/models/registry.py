"""Model plugin registry — product knowledge above RuntimeAdapter."""

from __future__ import annotations

from hydro_agent.execution.registry import RuntimeRegistry
from hydro_agent.models.contracts import HydroModelPlugin, ModelDescriptor
from hydro_agent.models.gr4j.plugin import Gr4jPlugin
from hydro_agent.models.xaj.plugin import XajPlugin
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


class ModelRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, HydroModelPlugin] = {}

    def register(self, plugin: HydroModelPlugin) -> None:
        model_id = plugin.descriptor.model_id
        if model_id in self._plugins:
            raise ValueError(f"model {model_id} already registered")
        self._plugins[model_id] = plugin

    def get(self, model_id: str) -> HydroModelPlugin:
        if model_id not in self._plugins:
            raise KeyError(f"unknown model {model_id}")
        return self._plugins[model_id]

    def list_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._plugins))

    def descriptors(self) -> tuple[ModelDescriptor, ...]:
        return tuple(self._plugins[mid].descriptor for mid in self.list_ids())

    def runtime_registry(self) -> RuntimeRegistry:
        registry = RuntimeRegistry()
        for plugin in self._plugins.values():
            registry.register(plugin.runtime_adapter)
        return registry

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        strategies: list = []
        for plugin in self._plugins.values():
            strategies.extend(plugin.strategy_registry().all_strategies())
        return CalibrationStrategyRegistry(strategies=tuple(strategies))

    def default_strategy_id(self, model_id: str) -> str:
        return self.get(model_id).descriptor.default_strategy_id

    def diagnosis_skill_id(self, model_id: str) -> str | None:
        return self.get(model_id).descriptor.diagnosis_skill_id


_DEFAULT: ModelRegistry | None = None


def default_model_registry() -> ModelRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        registry = ModelRegistry()
        registry.register(XajPlugin())
        registry.register(Gr4jPlugin())
        _DEFAULT = registry
    return _DEFAULT
