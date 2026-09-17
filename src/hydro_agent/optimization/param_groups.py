"""Parameter-group helpers — prefer model plugins; XAJ kept for compatibility."""

from __future__ import annotations

from typing import Literal

from hydro_agent.models.xaj.param_groups import (
    ALL_PARAM_GROUPS,
    XAJ_PARAM_GROUPS,
)
from hydro_agent.models.xaj.param_groups import (
    normalize_param_groups as normalize_xaj_param_groups,
)
from hydro_agent.models.xaj.param_groups import (
    resolve_param_names as resolve_xaj_param_names,
)

ParamGroup = str
ObjectiveName = Literal["nse", "peak", "composite"]
ALL_OBJECTIVES: tuple[ObjectiveName, ...] = ("nse", "peak", "composite")


def resolve_param_names(
    groups: tuple[str, ...] | list[str] | None,
    *,
    model_id: str = "xaj",
) -> tuple[str, ...]:
    if model_id == "xaj":
        return resolve_xaj_param_names(groups)
    from hydro_agent.models.registry import default_model_registry

    return default_model_registry().get(model_id).resolve_param_names(groups)


def normalize_param_groups(raw, *, model_id: str = "xaj") -> tuple[str, ...]:
    if model_id == "xaj":
        return normalize_xaj_param_groups(raw)
    from hydro_agent.models.registry import default_model_registry

    plugin = default_model_registry().get(model_id)
    if hasattr(plugin, "normalize_param_groups"):
        return plugin.normalize_param_groups(raw)  # type: ignore[attr-defined]
    if raw is None:
        return tuple(plugin.descriptor.parameter_groups)
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in raw if str(p).strip()]
    allowed = set(plugin.descriptor.parameter_groups)
    out: list[str] = []
    for part in parts or plugin.descriptor.parameter_groups:
        key = part.lower()
        if key not in allowed:
            raise KeyError(f"unknown {model_id} param group: {part}")
        if key not in out:
            out.append(key)
    return tuple(out)


__all__ = [
    "ALL_OBJECTIVES",
    "ALL_PARAM_GROUPS",
    "ObjectiveName",
    "ParamGroup",
    "XAJ_PARAM_GROUPS",
    "normalize_param_groups",
    "resolve_param_names",
]
