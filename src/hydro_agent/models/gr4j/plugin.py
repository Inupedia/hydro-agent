"""GR4J HydroModelPlugin — second model, same RuntimeAdapter boundary."""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import ModelDescriptor
from hydro_agent.models.gr4j.adapter import Gr4jRuntimeAdapter
from hydro_agent.models.gr4j.contracts import Gr4jBasin, Gr4jScheme
from hydro_agent.models.gr4j.engine import load_param_ranges, simulate
from hydro_agent.models.gr4j.param_groups import (
    ALL_PARAM_GROUPS,
    DEFAULT_GR4J_PARAMS,
    normalize_param_groups,
    resolve_param_names,
)
from hydro_agent.models.gr4j.strategies import GR4J_STRATEGIES
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


class Gr4jPlugin:
    descriptor = ModelDescriptor(
        model_id="gr4j",
        title="GR4J",
        required_forcings=("precipitation", "pet"),
        parameter_groups=ALL_PARAM_GROUPS,
        parameter_names=Gr4jScheme.PARAMETER_ORDER,
        default_strategy_id="gr4j-bounded-v1",
        strategy_ids=tuple(s.strategy_id for s in GR4J_STRATEGIES),
        diagnosis_skill_id="gr4j-calibration-diagnosis",
        supports_forecast=True,
        supports_calibration=True,
        supports_resume=True,
        default_warmup_days=30,
    )
    runtime_adapter = Gr4jRuntimeAdapter()

    def validate_scheme(self, config: dict) -> None:
        Gr4jScheme(
            model_id=config.get("model_id", "gr4j"),
            warmup_days=int(config["warmup_days"]),
            parameters=config["parameters"],
        )

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        return CalibrationStrategyRegistry(strategies=GR4J_STRATEGIES)

    def default_scheme_config(self) -> dict:
        return {
            "model_id": "gr4j",
            "warmup_days": self.descriptor.default_warmup_days,
            "parameters": dict(DEFAULT_GR4J_PARAMS),
        }

    def resolve_param_names(self, groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
        return resolve_param_names(groups)

    def normalize_param_groups(self, raw) -> tuple[str, ...]:
        return normalize_param_groups(raw)

    def parameter_bounds(self) -> dict[str, tuple[float, float]]:
        return load_param_ranges()

    def simulate(
        self,
        scheme_config: dict,
        basin: dict,
        forcing: Any,
        *,
        include_warmup: bool = False,
    ) -> Any:
        scheme = Gr4jScheme(
            model_id=scheme_config.get("model_id", "gr4j"),
            warmup_days=int(scheme_config["warmup_days"]),
            parameters=scheme_config["parameters"],
        )
        basin_model = Gr4jBasin.model_validate(basin)
        return simulate(scheme, basin_model, forcing, include_warmup=include_warmup)
