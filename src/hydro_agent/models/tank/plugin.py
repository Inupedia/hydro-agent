"""Classic multi-tank HydroModelPlugin (Sugawara-family 3-tank + discrete Nash)."""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import DiagnosisPlan, DiagnosisPolicy, ModelDescriptor
from hydro_agent.models.tank.adapter import TankRuntimeAdapter
from hydro_agent.models.tank.contracts import TankBasin, TankScheme
from hydro_agent.models.tank.engine import MODEL_SHA256, MODEL_VERSION, load_param_ranges, simulate
from hydro_agent.models.tank.param_groups import (
    ALL_PARAM_GROUPS,
    DEFAULT_TANK_PARAMS,
    DISCRETE_PARAMETER_NAMES,
    normalize_param_groups,
    resolve_param_names,
    snap_discrete_parameters,
)
from hydro_agent.models.tank.parity import REFERENCE_ORACLE
from hydro_agent.models.tank.strategies import TANK_STRATEGIES
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry


class TankPlugin:
    MODEL_VERSION = MODEL_VERSION
    MODEL_SHA256 = MODEL_SHA256
    discrete_parameter_names = DISCRETE_PARAMETER_NAMES
    descriptor = ModelDescriptor(
        model_id="tank",
        title="三层 Tank + Nash",
        required_forcings=("precipitation", "pet"),
        parameter_groups=ALL_PARAM_GROUPS,
        parameter_names=TankScheme.PARAMETER_ORDER,
        default_strategy_id="tank-bounded-v1",
        strategy_ids=tuple(s.strategy_id for s in TANK_STRATEGIES),
        diagnosis_skill_id="tank-calibration-diagnosis",
        diagnosis_policy=DiagnosisPolicy(
            measurement=DiagnosisPlan(
                strategy_id="tank-bounded-v1",
                param_groups=("surface", "intermediate", "base", "routing"),
            ),
            water_balance=DiagnosisPlan(
                strategy_id="tank-production-refine-v1",
                param_groups=("surface", "intermediate", "base"),
            ),
            timing=DiagnosisPlan(
                strategy_id="tank-routing-refine-v1",
                param_groups=("routing",),
            ),
            peak=DiagnosisPlan(
                strategy_id="tank-bounded-v1",
                param_groups=("surface", "routing"),
            ),
            composite=DiagnosisPlan(
                strategy_id="tank-bounded-v1",
                param_groups=("surface", "intermediate", "base", "routing"),
            ),
            local=DiagnosisPlan(
                strategy_id="tank-local-refine-v1",
                param_groups=("surface", "intermediate", "base", "routing"),
            ),
            fallback_strategy_ids=(
                "tank-bounded-v1",
                "tank-local-refine-v1",
                "tank-production-refine-v1",
            ),
        ),
        supports_forecast=True,
        supports_calibration=True,
        supports_resume=True,
        default_warmup_days=30,
        validation_status="source_verified",
        implementation_name="Hydro-Agent NumPy 3-tank + discrete Nash cascade",
        technical_reference=(
            "Sugawara-family tank structure (product-fixed 3 tanks + Nash); "
            f"parity vs {REFERENCE_ORACLE} (see models/tank/parity.py)"
        ),
        limitations=(
            "Product-fixed three-tank layout; not the unique classical four-tank Sugawara diagram",
            "Nash length N is discrete (integer 1–5); continuous samples are snapped before evaluation",
        ),
    )
    runtime_adapter = TankRuntimeAdapter()

    def validate_scheme(self, config: dict) -> None:
        parameters = snap_discrete_parameters(dict(config["parameters"]))
        TankScheme(
            model_id=config.get("model_id", "tank"),
            warmup_days=int(config["warmup_days"]),
            parameters=parameters,
        )

    def strategy_registry(self) -> CalibrationStrategyRegistry:
        return CalibrationStrategyRegistry(strategies=TANK_STRATEGIES)

    def default_scheme_config(self) -> dict:
        return {
            "model_id": "tank",
            "warmup_days": self.descriptor.default_warmup_days,
            "parameters": dict(DEFAULT_TANK_PARAMS),
        }

    def canonicalize_parameters(self, parameters: dict[str, float]) -> dict[str, float]:
        return snap_discrete_parameters(parameters)

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
        parameters = snap_discrete_parameters(dict(scheme_config["parameters"]))
        scheme = TankScheme(
            model_id=scheme_config.get("model_id", "tank"),
            warmup_days=int(scheme_config["warmup_days"]),
            parameters=parameters,
        )
        basin_model = TankBasin.model_validate(basin)
        return simulate(scheme, basin_model, forcing, include_warmup=include_warmup)
