"""Model plugin contracts: descriptor + runtime binding.

``RuntimeAdapter`` remains the execution boundary ("how to run"). Plugins add
the product knowledge that generic control-plane code must not hardcode:
parameter groups, default strategies, diagnosis skill id, and scheme defaults.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import Field

from hydro_agent.execution.adapter import RuntimeAdapter
from hydro_agent.execution.contracts import FrozenModel

if TYPE_CHECKING:
    from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


class ModelDescriptor(FrozenModel):
    model_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    required_forcings: tuple[str, ...] = ()
    parameter_groups: tuple[str, ...] = ()
    parameter_names: tuple[str, ...] = ()
    default_strategy_id: str = Field(min_length=1)
    strategy_ids: tuple[str, ...] = ()
    diagnosis_skill_id: str | None = None
    supports_forecast: bool = True
    supports_calibration: bool = True
    supports_resume: bool = True
    default_warmup_days: int = Field(default=30, ge=1)


@runtime_checkable
class HydroModelPlugin(Protocol):
    descriptor: ModelDescriptor
    runtime_adapter: RuntimeAdapter

    def validate_scheme(self, config: dict) -> None: ...

    def strategy_registry(self) -> CalibrationStrategyRegistry: ...

    def default_scheme_config(self) -> dict: ...

    def resolve_param_names(self, groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]: ...

    def parameter_bounds(self) -> dict[str, tuple[float, float]]: ...

    def simulate(
        self,
        scheme_config: dict,
        basin: dict,
        forcing: Any,
        *,
        include_warmup: bool = False,
    ) -> Any: ...
