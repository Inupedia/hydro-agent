"""HBV-light HydroModelPlugin."""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import DiagnosisPlan, DiagnosisPolicy, ModelDescriptor
from hydro_agent.models.hbv.adapter import HbvRuntimeAdapter
from hydro_agent.models.hbv.contracts import HbvBasin, HbvScheme
from hydro_agent.models.hbv.engine import MODEL_SHA256, MODEL_VERSION, load_param_ranges, simulate
from hydro_agent.models.hbv.param_groups import (
    ALL_PARAM_GROUPS,
    DEFAULT_HBV_PARAMS,
    normalize_param_groups,
    resolve_param_names,
)
from hydro_agent.models.hbv.strategies import HBV_STRATEGIES
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


class HbvPlugin:
    MODEL_VERSION = MODEL_VERSION
    MODEL_SHA256 = MODEL_SHA256
    descriptor = ModelDescriptor(
        model_id="hbv",
        title="HBV-light",
        required_forcings=("precipitation", "temperature", "pet"),
        parameter_groups=ALL_PARAM_GROUPS,
        parameter_names=HbvScheme.PARAMETER_ORDER,
        default_strategy_id="hbv-bounded-v1",
        strategy_ids=tuple(s.strategy_id for s in HBV_STRATEGIES),
        diagnosis_skill_id="hbv-calibration-diagnosis",
        diagnosis_policy=DiagnosisPolicy(
            measurement=DiagnosisPlan(
                strategy_id="hbv-bounded-v1",
                param_groups=("snow", "soil", "groundwater", "routing"),
            ),
            water_balance=DiagnosisPlan(
                strategy_id="hbv-water-balance-refine-v1",
                param_groups=("snow", "soil", "groundwater"),
            ),
            timing=DiagnosisPlan(
                strategy_id="hbv-routing-refine-v1",
                param_groups=("routing",),
            ),
            peak=DiagnosisPlan(
                strategy_id="hbv-bounded-v1",
                param_groups=("soil", "groundwater", "routing"),
            ),
            composite=DiagnosisPlan(
                strategy_id="hbv-bounded-v1",
                param_groups=("snow", "soil", "groundwater", "routing"),
            ),
            local=DiagnosisPlan(
                strategy_id="hbv-local-refine-v1",
                param_groups=("snow", "soil", "groundwater", "routing"),
            ),
            fallback_strategy_ids=(
                "hbv-bounded-v1",
                "hbv-local-refine-v1",
                "hbv-water-balance-refine-v1",
            ),
        ),
        supports_forecast=True,
        supports_calibration=True,
        supports_resume=True,
        default_warmup_days=30,
    )
    runtime_adapter = HbvRuntimeAdapter()

    def validate_scheme(self, config: dict) -> None:
        HbvScheme(
            model_id=config.get("model_id", "hbv"),
            warmup_days=int(config["warmup_days"]),
            parameters=config["parameters"],
        )

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        return CalibrationStrategyRegistry(strategies=HBV_STRATEGIES)

    def default_scheme_config(self) -> dict:
        return {
            "model_id": "hbv",
            "warmup_days": self.descriptor.default_warmup_days,
            "parameters": dict(DEFAULT_HBV_PARAMS),
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
        scheme = HbvScheme(
            model_id=scheme_config.get("model_id", "hbv"),
            warmup_days=int(scheme_config["warmup_days"]),
            parameters=scheme_config["parameters"],
        )
        basin_model = HbvBasin.model_validate(basin)
        return simulate(scheme, basin_model, forcing, include_warmup=include_warmup)
