"""GR4J HydroModelPlugin — second model, same RuntimeAdapter boundary."""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import DiagnosisPlan, DiagnosisPolicy, ModelDescriptor
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
        diagnosis_policy=DiagnosisPolicy(
            measurement=DiagnosisPlan(
                strategy_id="gr4j-bounded-v1",
                param_groups=("production", "exchange", "routing"),
            ),
            water_balance=DiagnosisPlan(
                strategy_id="gr4j-production-refine-v1",
                param_groups=("production", "exchange"),
            ),
            timing=DiagnosisPlan(
                strategy_id="gr4j-routing-refine-v1",
                param_groups=("routing",),
            ),
            peak=DiagnosisPlan(
                strategy_id="gr4j-bounded-v1",
                param_groups=("production", "routing"),
            ),
            composite=DiagnosisPlan(
                strategy_id="gr4j-bounded-v1",
                param_groups=("production", "exchange", "routing"),
            ),
            local=DiagnosisPlan(
                strategy_id="gr4j-local-refine-v1",
                param_groups=("production", "exchange", "routing"),
            ),
            fallback_strategy_ids=(
                "gr4j-bounded-v1",
                "gr4j-local-refine-v1",
                "gr4j-production-refine-v1",
            ),
        ),
        supports_forecast=True,
        supports_calibration=True,
        supports_resume=True,
        default_warmup_days=30,
        validation_status="source_verified",
        implementation_name="Hydro-Agent NumPy GR4J",
        technical_reference=(
            "Perrin, Michel & Andréassian (2003), DOI 10.1016/S0022-1694(03)00225-7; "
            "parity vs GRsuite/airGR-1.7.9-aligned (see models/gr4j/parity.py)"
        ),
        limitations=(
            "日尺度集总结构，无雪过程；传统 ModelPlan 资料链仍可能只覆盖内置演示流域",
        ),
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
