"""NOAA-OWP SAC-SMA HydroModelPlugin (model_id ``sac-sma``)."""

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
    DEFAULT_SAC_SMA_ROUTING,
    FULL_PARAM_GROUPS,
    normalize_param_groups,
    resolve_param_names,
)
from hydro_agent.models.sacsma.parity import REFERENCE_ORACLE
from hydro_agent.models.sacsma.strategies import SAC_SMA_STRATEGIES
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


def _canonicalize_parameters(values: dict[str, float]) -> dict[str, float]:
    """Normalize coupled SAC-SMA parameters to feasible ranges."""
    out = {
        name: min(max(float(value), 0.0), 1.0)
        if name
        in {
            "UZK",
            "LZSK",
            "LZPK",
            "PCTIM",
            "ADIMP",
            "RIVA",
            "PFREE",
            "SIDE",
            "RSERV",
        }
        else float(value)
        for name, value in values.items()
    }
    if out.get("UZTWM", 1.0) <= 0.0:
        out["UZTWM"] = 1.0
    if out.get("UZFWM", 1.0) <= 0.0:
        out["UZFWM"] = 1.0
    if out.get("LZTWM", 1.0) <= 0.0:
        out["LZTWM"] = 1.0
    if out.get("LZFSM", 1.0) <= 0.0:
        out["LZFSM"] = 1.0
    if out.get("LZFPM", 1.0) <= 0.0:
        out["LZFPM"] = 1.0
    if out.get("ZPERC", 1.0) <= 0.0:
        out["ZPERC"] = 1.0
    if out.get("REXP", 0.0) < 0.0:
        out["REXP"] = 0.0
    if out.get("PCTIM", 0.0) + out.get("ADIMP", 0.0) >= 1.0:
        scale = 0.99 / max(out.get("PCTIM", 0.0) + out.get("ADIMP", 0.0), 1e-12)
        out["PCTIM"] = min(out.get("PCTIM", 0.0) * scale, 1.0)
        out["ADIMP"] = min(out.get("ADIMP", 0.0) * scale, 1.0)
    return out


class SacSmaPlugin:
    MODEL_VERSION = MODEL_VERSION
    MODEL_SHA256 = MODEL_SHA256
    descriptor = ModelDescriptor(
        model_id="sac-sma",
        title="NOAA-OWP SAC-SMA（16 参数无冻土核）",
        required_forcings=("precipitation", "pet"),
        parameter_groups=ALL_PARAM_GROUPS,
        parameter_names=SacSmaScheme.PARAMETER_ORDER,
        default_strategy_id="sac-sma-bounded-v1",
        strategy_ids=tuple(s.strategy_id for s in SAC_SMA_STRATEGIES),
        diagnosis_skill_id="sac-sma-calibration-diagnosis",
        diagnosis_policy=DiagnosisPolicy(
            measurement=DiagnosisPlan(
                strategy_id="sac-sma-bounded-v1",
                param_groups=FULL_PARAM_GROUPS,
            ),
            water_balance=DiagnosisPlan(
                strategy_id="sac-sma-water-balance-refine-v1",
                param_groups=("upper", "lower", "percolation", "evap", "baseflow"),
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
                param_groups=FULL_PARAM_GROUPS,
            ),
            local=DiagnosisPlan(
                strategy_id="sac-sma-local-refine-v1",
                param_groups=FULL_PARAM_GROUPS,
            ),
            fallback_strategy_ids=(
                "sac-sma-bounded-v1",
                "sac-sma-local-refine-v1",
                "sac-sma-water-balance-refine-v1",
            ),
        ),
        supports_forecast=True,
        supports_calibration=True,
        supports_resume=True,
        default_warmup_days=730,
        validation_status="source_verified",
        implementation_name="Hydro-Agent NumPy NOAA-OWP SAC-SMA",
        technical_reference=(
            "NOAA-OWP sac-sma (SAC1/EXSAC); Burnash et al. (1973); "
            f"parity vs {REFERENCE_ORACLE}; "
            "see models/sacsma/parity.py"
        ),
        limitations=(
            "仅覆盖 NOAA-OWP SAC1 的无冻土土壤湿度核算，不含积雪、融雪和冻土过程",
            "默认使用 730 天冷启动预热；正式实验仍须检查状态稳定性",
            "输出在 NOAA TCI 之外使用仓库自定义日尺度三角单位线；HOURS<=24 在日尺度退化为同日响应",
        ),
    )
    runtime_adapter = SacSmaRuntimeAdapter()

    def validate_scheme(self, config: dict) -> None:
        SacSmaScheme(
            model_id=config.get("model_id", "sac-sma"),
            warmup_days=int(config["warmup_days"]),
            routing=config.get("routing", DEFAULT_SAC_SMA_ROUTING),
            parameters=config["parameters"],
        )

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        return CalibrationStrategyRegistry(strategies=SAC_SMA_STRATEGIES)

    def default_scheme_config(self) -> dict:
        return {
            "model_id": "sac-sma",
            "warmup_days": self.descriptor.default_warmup_days,
            "routing": dict(DEFAULT_SAC_SMA_ROUTING),
            "parameters": dict(DEFAULT_SAC_SMA_PARAMS),
        }

    def resolve_param_names(self, groups: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
        return resolve_param_names(groups)

    def normalize_param_groups(self, raw) -> tuple[str, ...]:
        return normalize_param_groups(raw)

    def parameter_bounds(self) -> dict[str, tuple[float, float]]:
        return load_param_ranges()

    def canonicalize_parameters(self, values: dict[str, float]) -> dict[str, float]:
        return _canonicalize_parameters(values)

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
            routing=scheme_config.get("routing", DEFAULT_SAC_SMA_ROUTING),
            parameters=scheme_config["parameters"],
        )
        basin_model = SacSmaBasin.model_validate(basin)
        return simulate(scheme, basin_model, forcing, include_warmup=include_warmup)
