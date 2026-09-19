"""Deterministic computation-unit candidate construction.

Candidate construction never creates polygon geometry. It only references the basin
boundary or deterministic topology units already produced by trusted GIS tools.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.hydrology.spatial_profile import BasinSpatialProfile


class UnitSchemeCandidate(FrozenModel):
    candidate_id: str
    kind: Literal["lumped", "topology_subbasin", "heterogeneity_aware"]
    unit_ids: tuple[str, ...]
    unit_count: int = Field(ge=1)
    area_distribution_km2: tuple[float, ...]
    evidence_refs: tuple[str, ...]
    preserved_contrasts: tuple[str, ...] = ()
    lost_contrasts: tuple[str, ...] = ()
    complexity_notes: tuple[str, ...] = ()


def _unit_sort_key(unit_id: str) -> tuple[int, int | str]:
    try:
        return (0, int(unit_id))
    except ValueError:
        return (1, unit_id)


def _normalized_units(
    topology_units: Iterable[Mapping[str, object]],
) -> tuple[tuple[str, float, int | None], ...]:
    rows: list[tuple[str, float, int | None]] = []
    seen: set[str] = set()
    for raw in topology_units:
        if "unit_id" not in raw:
            raise ValueError("topology unit missing unit_id")
        unit_id = str(raw["unit_id"]).strip()
        if not unit_id:
            raise ValueError("topology unit_id cannot be empty")
        if unit_id in seen:
            raise ValueError(f"duplicate topology unit_id: {unit_id}")
        seen.add(unit_id)

        area_raw = raw.get("area_km2", raw.get("area"))
        if area_raw is None:
            raise ValueError(f"topology unit {unit_id} missing area_km2")
        area = float(area_raw)
        if not math.isfinite(area) or area <= 0:
            raise ValueError(f"topology unit {unit_id} area_km2 must be positive")

        downstream_raw = raw.get("downstream_unit_id")
        downstream = None if downstream_raw is None else int(downstream_raw)
        rows.append((unit_id, area, downstream))

    if not rows:
        raise ValueError("at least one topology unit is required")
    return tuple(sorted(rows, key=lambda row: _unit_sort_key(row[0])))


def _known_contrasts(
    profile: BasinSpatialProfile,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    contrasts: list[str] = []
    refs: list[str] = []

    if (
        profile.elevation.status == "available"
        and profile.elevation.std is not None
        and profile.elevation.std > 0
    ):
        contrasts.append("elevation")
        refs.append("elevation.std")

    if (
        profile.precipitation.status == "available"
        and profile.precipitation.cv is not None
        and profile.precipitation.cv > 0
    ):
        contrasts.append("precipitation")
        refs.append("precipitation.cv")

    if (
        profile.land_cover.status == "available"
        and len(profile.land_cover.fractions) > 1
    ):
        contrasts.append("land_cover")
        refs.append("land_cover.fractions")

    return tuple(contrasts), tuple(refs)


def _candidate_id(
    *,
    kind: str,
    unit_ids: tuple[str, ...],
    areas: tuple[float, ...],
    evidence_refs: tuple[str, ...],
    preserved_contrasts: tuple[str, ...],
) -> str:
    payload = {
        "kind": kind,
        "unit_ids": list(unit_ids),
        "areas": [round(float(value), 9) for value in areas],
        "evidence_refs": list(evidence_refs),
        "preserved_contrasts": list(preserved_contrasts),
    }
    digest = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"units-{kind.replace('_', '-')}-{digest}"


def _make_candidate(
    *,
    kind: Literal["lumped", "topology_subbasin", "heterogeneity_aware"],
    unit_ids: tuple[str, ...],
    areas: tuple[float, ...],
    evidence_refs: tuple[str, ...],
    preserved_contrasts: tuple[str, ...] = (),
    lost_contrasts: tuple[str, ...] = (),
    complexity_notes: tuple[str, ...] = (),
) -> UnitSchemeCandidate:
    return UnitSchemeCandidate(
        candidate_id=_candidate_id(
            kind=kind,
            unit_ids=unit_ids,
            areas=areas,
            evidence_refs=evidence_refs,
            preserved_contrasts=preserved_contrasts,
        ),
        kind=kind,
        unit_ids=unit_ids,
        unit_count=len(unit_ids),
        area_distribution_km2=areas,
        evidence_refs=evidence_refs,
        preserved_contrasts=preserved_contrasts,
        lost_contrasts=lost_contrasts,
        complexity_notes=complexity_notes,
    )


def build_unit_scheme_candidates(
    *,
    spatial_profile: BasinSpatialProfile,
    topology_units: Iterable[Mapping[str, object]],
    max_units: int = 8,
) -> tuple[UnitSchemeCandidate, ...]:
    """Build deterministic, geometry-free scheme candidates.

    The heterogeneity-aware V1 candidate deliberately reuses existing topology
    polygons. Spatial evidence may justify retaining the multi-unit resolution,
    but it never authorizes this function (or an LLM) to draw a new boundary.
    """

    if max_units < 1:
        raise ValueError("max_units must be >= 1")

    units = _normalized_units(topology_units)
    unit_ids = tuple(row[0] for row in units)
    areas = tuple(float(row[1]) for row in units)
    total_area = float(sum(areas))
    contrasts, contrast_refs = _known_contrasts(spatial_profile)

    lumped_refs = (
        ("drainage.area_km2",)
        if spatial_profile.drainage.area_km2 is not None
        else ("topology.area_distribution_km2",)
    )
    candidates: list[UnitSchemeCandidate] = [
        _make_candidate(
            kind="lumped",
            unit_ids=("basin",),
            areas=(total_area,),
            evidence_refs=lumped_refs,
            lost_contrasts=contrasts,
            complexity_notes=(
                "single full-basin unit",
                "simplest representation; spatial contrasts are not retained",
            ),
        )
    ]

    topology_refs = ["topology.unit_ids", "topology.area_distribution_km2"]
    if any(row[2] is not None for row in units):
        topology_refs.append("topology.downstream_unit_id")
    candidates.append(
        _make_candidate(
            kind="topology_subbasin",
            unit_ids=unit_ids,
            areas=areas,
            evidence_refs=tuple(topology_refs),
            preserved_contrasts=("drainage_topology",),
            complexity_notes=(
                "uses deterministic GIS sub-basin polygons unchanged",
                f"{len(unit_ids)} existing topology units",
            ),
        )
    )

    if contrasts and 1 < len(unit_ids) <= max_units:
        candidates.append(
            _make_candidate(
                kind="heterogeneity_aware",
                unit_ids=unit_ids,
                areas=areas,
                evidence_refs=tuple((*contrast_refs, "topology.unit_ids")),
                preserved_contrasts=contrasts,
                complexity_notes=(
                    "retains existing topology polygons to preserve known spatial contrasts",
                    "does not create, split, or redraw polygon geometry",
                ),
            )
        )

    return tuple(candidates)
