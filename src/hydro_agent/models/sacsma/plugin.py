"""Simplified SAC-SMA HydroModelPlugin (model_id ``sac-sma``)."""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import DiagnosisPlan, DiagnosisPolicy, ModelDescriptor
from hydro_agent.models.sacsma.adapter import SacSmaRuntimeAdapter
from hydro_agent.models.sacsma.contracts import SacSmaBasin, SacSmaScheme
from hydro_agent.models.sacsma.engine import (
    MODEL_SHA256,
    MODEL_VERSION,
    load_param_ranges,
    simulate,
)
from hydro_agent.models.sacsma.param_groups import (
    ALL_PARAM_GROUPS,
    DEFAULT_SAC_SMA_PARAMS,
    normalize_param_groups,
    resolve_param_names,
)
from hydro_agent.models.sacsma.strategies import SAC_SMA_STRATEGIES
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


class SacSmaPlugin:
    MODEL_VERSION = MODEL_VERSION
    MODEL_SHA256 = MODEL_SHA256
    descriptor = ModelDescriptor(
        model_id="sac-sma",
        title="SAC-SMA-inspired reduced（实验实现）",
        required_forcings=("precipitation", "pet"),
        parameter_groups=ALL_PARAM_GROUPS,
        parameter_names=SacSmaScheme.PARAMETER_ORDER,
        default_strategy_id="sac-sma-bounded-v1",
        strategy_ids=tuple(s.strategy_id for s in SAC_SMA_STRATEGIES),
        diagnosis_skill_id="sac-sma-calibration-diagnosis",
        diagnosis_policy=DiagnosisPolicy(
            measurement=DiagnosisPlan(
                strategy_id="sac-sma-bounded-v1",
                param_groups=("upper", "lower", "percolation", "routing"),
            ),
            water_balance=DiagnosisPlan(
                strategy_id="sac-sma-water-balance-refine-v1",
                param_groups=("upper", "lower", "percolation"),
            ),
            timing=DiagnosisPlan(
                strategy_id="sac-sma-routing-refine-v1",
                param_groups=("routing",),
            ),
            peak=DiagnosisPlan(
                strategy_id="sac-sma-bounded-v1",
                param_groups=("upper", "routing"),
            ),
            composite=DiagnosisPlan(
                strategy_id="sac-sma-bounded-v1",
                param_groups=("upper", "lower", "percolation", "routing"),
            ),
            local=DiagnosisPlan(
                strategy_id="sac-sma-local-refine-v1",
                param_groups=("upper", "lower", "percolation", "routing"),
            ),
            fallback_strategy_ids=(
                "sac-sma-bounded-v1",
                "sac-sma-local-refine-v1",
                "sac-sma-water-balance-refine-v1",
            ),
        ),
        supports_forecast=True,
        supports_calibration=False,
        supports_resume=True,
        default_warmup_days=30,
        validation_status="experimental_variant",
        implementation_name="Hydro-Agent reduced SAC-SMA-inspired variant",
        technical_reference="Burnash et al. (1973); NOAA-OWP sac-sma",
        limitations=(
            "省略 ADIMP、PFREE、RIVA、SIDE、RSERV 等标准 SAC-SMA 参数和过程",
            "当前渗漏和路由方程未与 NOAA-OWP SAC-SMA 完成 parity",
        ),
    )
    runtime_adapter = SacSmaRuntimeAdapter()

    def validate_scheme(self, config: dict) -> None:
        SacSmaScheme(
            model_id=config.get("model_id", "sac-sma"),
            warmup_days=int(config["warmup_days"]),
            parameters=config["parameters"],
        )

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        return CalibrationStrategyRegistry(strategies=SAC_SMA_STRATEGIES)

    def default_scheme_config(self) -> dict:
        return {
            "model_id": "sac-sma",
            "warmup_days": self.descriptor.default_warmup_days,
            "parameters": dict(DEFAULT_SAC_SMA_PARAMS),
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
        scheme = SacSmaScheme(
            model_id=scheme_config.get("model_id", "sac-sma"),
            warmup_days=int(scheme_config["warmup_days"]),
            parameters=scheme_config["parameters"],
        )
        basin_model = SacSmaBasin.model_validate(basin)
        return simulate(scheme, basin_model, forcing, include_warmup=include_warmup)
