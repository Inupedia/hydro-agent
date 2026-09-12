"""Search-space evidence for calibration experiments.

Boundary proximity is treated as numerical evidence, not as permission to expand
XAJ parameter bounds. Expert knowledge decides how that evidence should affect
the next experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BoundarySide = Literal["lower", "upper"]
BoundaryScope = Literal["local", "absolute"]

DEFAULT_NEAR_FRACTION = 0.02


@dataclass(frozen=True)
class SearchBoundaryHit:
    parameter: str
    side: BoundarySide
    scope: BoundaryScope
    value: float
    search_bound: float
    absolute_bound: float
    normalized_distance: float


@dataclass(frozen=True)
class SearchBoundaryEvidence:
    hits: tuple[SearchBoundaryHit, ...]
    near_fraction: float

    @property
    def local_hits(self) -> tuple[str, ...]:
        return tuple(hit.parameter for hit in self.hits if hit.scope == "local")

    @property
    def absolute_hits(self) -> tuple[str, ...]:
        return tuple(hit.parameter for hit in self.hits if hit.scope == "absolute")

    def as_dict(self) -> dict[str, object]:
        return {
            "near_fraction": self.near_fraction,
            "local_hits": list(self.local_hits),
            "absolute_hits": list(self.absolute_hits),
            "hits": [
                {
                    "parameter": hit.parameter,
                    "side": hit.side,
                    "scope": hit.scope,
                    "value": hit.value,
                    "search_bound": hit.search_bound,
                    "absolute_bound": hit.absolute_bound,
                    "normalized_distance": hit.normalized_distance,
                }
                for hit in self.hits
            ],
        }


def analyze_search_boundaries(
    *,
    values: dict[str, float],
    search_bounds: dict[str, tuple[float, float]],
    absolute_bounds: dict[str, tuple[float, float]],
    near_fraction: float = DEFAULT_NEAR_FRACTION,
) -> SearchBoundaryEvidence:
    """Classify selected parameters near a search boundary.

    A hit is ``absolute`` only when it is also close to the teacher/kernel bound.
    Otherwise it is a ``local`` hit: the current local search window ended before
    the absolute admissible range did. This distinction allows a later expert
    rule to broaden a local window without silently expanding physical bounds.
    """

    if not 0 <= near_fraction < 0.5:
        raise ValueError("near_fraction must be in [0, 0.5)")

    hits: list[SearchBoundaryHit] = []
    for name, (search_low_raw, search_high_raw) in search_bounds.items():
        if name not in values or name not in absolute_bounds:
            continue
        value = float(values[name])
        search_low, search_high = float(search_low_raw), float(search_high_raw)
        absolute_low, absolute_high = (float(v) for v in absolute_bounds[name])
        search_span = search_high - search_low
        absolute_span = absolute_high - absolute_low
        if search_span <= 0 or absolute_span <= 0:
            raise ValueError(f"invalid bounds for {name}")

        lower_distance = abs(value - search_low) / search_span
        upper_distance = abs(search_high - value) / search_span
        if min(lower_distance, upper_distance) > near_fraction:
            continue

        if lower_distance <= upper_distance:
            side: BoundarySide = "lower"
            search_bound = search_low
            absolute_bound = absolute_low
            absolute_distance = abs(value - absolute_low) / absolute_span
        else:
            side = "upper"
            search_bound = search_high
            absolute_bound = absolute_high
            absolute_distance = abs(absolute_high - value) / absolute_span

        scope: BoundaryScope = "absolute" if absolute_distance <= near_fraction else "local"
        hits.append(
            SearchBoundaryHit(
                parameter=name,
                side=side,
                scope=scope,
                value=value,
                search_bound=search_bound,
                absolute_bound=absolute_bound,
                normalized_distance=min(lower_distance, upper_distance),
            )
        )

    return SearchBoundaryEvidence(hits=tuple(hits), near_fraction=float(near_fraction))
