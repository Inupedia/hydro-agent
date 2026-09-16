"""Model-scoped diagnosis → strategy/param-group defaults.

Control-plane diagnosis must not hardcode XAJ strategy ids or groups.
Plugins own the vocabulary; this module maps shared error phenotypes onto
each model's registered strategies.
"""

from __future__ import annotations

from typing import Any


def resolve_model_id(*sources: Any, default: str = "xaj") -> str:
    for source in sources:
        if isinstance(source, dict):
            raw = source.get("model_id")
            if raw:
                return str(raw)
        elif isinstance(source, str) and source.strip():
            return source.strip()
    return default


def all_param_groups(model_id: str) -> list[str]:
    try:
        from hydro_agent.models.registry import default_model_registry

        return list(default_model_registry().get(model_id).descriptor.parameter_groups)
    except KeyError:
        if model_id == "gr4j":
            return ["production", "exchange", "routing"]
        return ["evap", "runoff", "routing"]


def allowed_param_groups(model_id: str | None = None) -> set[str]:
    if model_id:
        return set(all_param_groups(model_id))
    # Union used when model is unknown but groups must not be silently dropped.
    return {
        "evap",
        "runoff",
        "routing",
        "production",
        "exchange",
        "snow",
        "soil",
        "groundwater",
    }


def measurement_diagnosis_plan(model_id: str) -> tuple[str, list[str]]:
    """Broad, policy-neutral first experiment after measurement-only diagnosis."""

    groups = all_param_groups(model_id)
    if model_id == "gr4j":
        return "gr4j-bounded-v1", groups
    return "xaj-hydro-composite-v1", groups


def water_balance_plan(model_id: str) -> tuple[str, list[str]]:
    if model_id == "gr4j":
        return "gr4j-production-refine-v1", ["production", "exchange"]
    return "xaj-water-balance-v1", ["evap", "runoff"]


def timing_plan(model_id: str) -> tuple[str, list[str]]:
    if model_id == "gr4j":
        return "gr4j-routing-refine-v1", ["routing"]
    return "xaj-routing-refine-v1", ["routing"]


def peak_plan(model_id: str) -> tuple[str, list[str]]:
    if model_id == "gr4j":
        return "gr4j-bounded-v1", ["production", "routing"]
    return "xaj-peak-bias-v1", ["runoff", "routing"]


def composite_plan(model_id: str) -> tuple[str, list[str]]:
    groups = all_param_groups(model_id)
    if model_id == "gr4j":
        return "gr4j-bounded-v1", groups
    return "xaj-hydro-composite-v1", groups


def local_refine_plan(model_id: str) -> tuple[str, list[str]]:
    groups = all_param_groups(model_id)
    if model_id == "gr4j":
        return "gr4j-local-refine-v1", groups
    return "xaj-local-refine-v1", groups


def broadened_plan(model_id: str) -> str:
    return f"{model_id}-broadened-refine-v1"


def bounded_plan(model_id: str) -> tuple[str, list[str]]:
    return f"{model_id}-bounded-v1", all_param_groups(model_id)


def planner_fallbacks(model_id: str) -> tuple[str, ...]:
    if model_id == "gr4j":
        return (
            "gr4j-bounded-v1",
            "gr4j-local-refine-v1",
            "gr4j-production-refine-v1",
        )
    return (
        "xaj-hydro-composite-v1",
        "xaj-bounded-v1",
        "xaj-local-refine-v1",
    )
