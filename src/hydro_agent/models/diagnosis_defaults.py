"""Model-scoped diagnosis → strategy/param-group defaults.

Phenotype → experiment mapping lives on each plugin's ``DiagnosisPolicy``.
This module only resolves the active model and reads that policy.
"""

from __future__ import annotations

from typing import Any

from hydro_agent.models.contracts import DiagnosisPhenotype


def resolve_model_id(*sources: Any, default: str = "xaj") -> str:
    for source in sources:
        if isinstance(source, dict):
            raw = source.get("model_id")
            if raw:
                return str(raw)
        elif isinstance(source, str) and source.strip():
            return source.strip()
    return default


def model_id_from_strategy_id(strategy_id: str) -> str | None:
    """Map ``sac-sma-bounded-v1`` to ``sac-sma`` using registered plugins."""

    token = str(strategy_id or "").strip()
    if not token:
        return None
    try:
        from hydro_agent.models.registry import default_model_registry

        ids = sorted(default_model_registry().list_ids(), key=len, reverse=True)
    except Exception:  # noqa: BLE001
        ids = []
    for model_id in ids:
        if token == model_id or token.startswith(f"{model_id}-"):
            return model_id
    if "-" in token:
        return token.rsplit("-", 1)[0] if token.count("-") == 1 else token.split("-", 1)[0]
    return token


def _plugin(model_id: str):
    from hydro_agent.models.registry import default_model_registry

    return default_model_registry().get(model_id)


def all_param_groups(model_id: str) -> list[str]:
    try:
        return list(_plugin(model_id).descriptor.parameter_groups)
    except KeyError:
        return []


def allowed_param_groups(model_id: str | None = None) -> set[str]:
    if model_id:
        groups = all_param_groups(model_id)
        if groups:
            return set(groups)
    # Union fallback when model is unknown but groups must not be silently dropped.
    return {
        "evap",
        "runoff",
        "routing",
        "production",
        "exchange",
        "snow",
        "soil",
        "groundwater",
        "surface",
        "intermediate",
        "base",
        "upper",
        "lower",
        "percolation",
    }


def _plan(model_id: str, phenotype: DiagnosisPhenotype) -> tuple[str, list[str]]:
    plugin = _plugin(model_id)
    policy = plugin.descriptor.diagnosis_policy
    if policy is None:
        groups = list(plugin.descriptor.parameter_groups)
        return plugin.descriptor.default_strategy_id, groups
    plan = policy.plan_for(phenotype)
    return plan.strategy_id, list(plan.param_groups)


def measurement_diagnosis_plan(model_id: str) -> tuple[str, list[str]]:
    return _plan(model_id, "measurement")


def water_balance_plan(model_id: str) -> tuple[str, list[str]]:
    return _plan(model_id, "water_balance")


def timing_plan(model_id: str) -> tuple[str, list[str]]:
    return _plan(model_id, "timing")


def peak_plan(model_id: str) -> tuple[str, list[str]]:
    return _plan(model_id, "peak")


def composite_plan(model_id: str) -> tuple[str, list[str]]:
    return _plan(model_id, "composite")


def local_refine_plan(model_id: str) -> tuple[str, list[str]]:
    return _plan(model_id, "local")


def broadened_plan(model_id: str) -> str:
    return f"{model_id}-broadened-refine-v1"


def bounded_plan(model_id: str) -> tuple[str, list[str]]:
    return f"{model_id}-bounded-v1", all_param_groups(model_id)


def planner_fallbacks(model_id: str) -> tuple[str, ...]:
    try:
        plugin = _plugin(model_id)
    except KeyError:
        return (f"{model_id}-bounded-v1",)
    policy = plugin.descriptor.diagnosis_policy
    if policy and policy.fallback_strategy_ids:
        return policy.fallback_strategy_ids
    return (plugin.descriptor.default_strategy_id,)
