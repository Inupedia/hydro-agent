"""XAJ as the first HydroModelPlugin — RuntimeAdapter unchanged."""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import ModelDescriptor
from hydro_agent.models.xaj.adapter import XajRuntimeAdapter
from hydro_agent.models.xaj.contracts import XajBasin, XajScheme
from hydro_agent.models.xaj.param_groups import (
    ALL_PARAM_GROUPS,
    normalize_param_groups,
    resolve_param_names,
)
from hydro_agent.models.xaj.upstream import load_param_ranges, simulate
from hydro_agent.optimization.strategies import (
    XAJ_BOUNDED_V1,
    XAJ_BROADENED_REFINE_V1,
    XAJ_HYDRO_COMPOSITE_V1,
    XAJ_HYDROLOGIST_MANUAL_V1,
    XAJ_LOCAL_REFINE_V1,
    XAJ_PEAK_BIAS_V1,
    XAJ_RANDOM_SEARCH_V1,
    XAJ_ROUTING_REFINE_V1,
    XAJ_SCEUA_BENCHMARK_V1,
    XAJ_WATER_BALANCE_V1,
    CalibrationStrategyRegistry,
)

DEFAULT_XAJ_PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}

_XAJ_STRATEGIES = (
    XAJ_BOUNDED_V1,
    XAJ_PEAK_BIAS_V1,
    XAJ_LOCAL_REFINE_V1,
    XAJ_WATER_BALANCE_V1,
    XAJ_ROUTING_REFINE_V1,
    XAJ_HYDRO_COMPOSITE_V1,
    XAJ_BROADENED_REFINE_V1,
    XAJ_SCEUA_BENCHMARK_V1,
    XAJ_RANDOM_SEARCH_V1,
    XAJ_HYDROLOGIST_MANUAL_V1,
)


class XajPlugin:
    descriptor = ModelDescriptor(
        model_id="xaj",
        title="新安江模型",
        required_forcings=("precipitation", "pet"),
        parameter_groups=ALL_PARAM_GROUPS,
        parameter_names=XajScheme.PARAMETER_ORDER,
        default_strategy_id="xaj-bounded-v1",
        strategy_ids=tuple(s.strategy_id for s in _XAJ_STRATEGIES),
        diagnosis_skill_id="xaj-calibration-diagnosis",
        supports_forecast=True,
        supports_calibration=True,
        supports_resume=True,
        default_warmup_days=30,
    )
    runtime_adapter = XajRuntimeAdapter()

    def validate_scheme(self, config: dict) -> None:
        XajScheme(
            model_id=config.get("model_id", "xaj"),
            warmup_days=int(config["warmup_days"]),
            parameters=config["parameters"],
            routing=config.get("routing") or {},
        )

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        return CalibrationStrategyRegistry(strategies=_XAJ_STRATEGIES)

    def default_scheme_config(self) -> dict:
        return {
            "model_id": "xaj",
            "warmup_days": self.descriptor.default_warmup_days,
            "parameters": dict(DEFAULT_XAJ_PARAMS),
            "routing": {"dp": 0, "ke": 24.0, "xe": 0.2},
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
        scheme = XajScheme(
            model_id=scheme_config.get("model_id", "xaj"),
            warmup_days=int(scheme_config["warmup_days"]),
            parameters=scheme_config["parameters"],
            routing=scheme_config.get("routing") or {},
        )
        basin_model = XajBasin.model_validate(basin)
        return simulate(scheme, basin_model, forcing, include_warmup=include_warmup)
