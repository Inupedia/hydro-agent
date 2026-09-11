from __future__ import annotations

from functools import lru_cache

from hydro_agent.workflow.definition import load_definition


@lru_cache(maxsize=8)
def _sets(version: str | None = None) -> dict[str, frozenset[str]]:
    definition = load_definition(version)
    phase: dict[str, set[str]] = {name: set() for name in definition.phases}
    implemented: set[str] = set()
    exploratory: set[str] = set()
    closeout: set[str] = set()
    for action in definition.actions:
        if action.kind != "runtime":
            continue
        if action.enabled:
            implemented.add(action.id)
            for name in action.phases:
                phase[name].add(action.id)
            if action.role in {"exploratory", "both"}:
                exploratory.add(action.id)
            if action.role in {"closeout", "both"}:
                closeout.add(action.id)
    return {
        "implemented": frozenset(implemented),
        "exploratory": frozenset(exploratory),
        "closeout": frozenset(closeout),
        **{f"phase:{name}": frozenset(codes) for name, codes in phase.items()},
    }


def implemented_action_ids(version: str | None = None) -> frozenset[str]:
    return _sets(version)["implemented"]


def exploratory_action_ids(version: str | None = None) -> frozenset[str]:
    return _sets(version)["exploratory"]


def closeout_action_ids(version: str | None = None) -> frozenset[str]:
    return _sets(version)["closeout"]


def phase_action_ids(phase: str, version: str | None = None) -> frozenset[str]:
    return _sets(version).get(f"phase:{phase}", frozenset())


def clear_catalog_cache() -> None:
    _sets.cache_clear()
