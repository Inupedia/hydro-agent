from __future__ import annotations

from math import ceil
from typing import Literal

from hydro_agent.execution.contracts import FrozenModel

ExperienceConvergenceStatus = Literal[
    "learning",
    "converging",
    "converged",
    "reopened",
]

_STRUCTURAL = {"CREATE", "MERGE", "SPLIT", "SUPERSEDE"}


class ConvergenceSummary(FrozenModel):
    status: ExperienceConvergenceStatus
    window: int
    event_count: int
    structural_count: int
    non_structural_count: int
    recent_event_types: tuple[str, ...]
    reason: str


def compute_convergence(
    events,
    *,
    window: int = 10,
) -> ConvergenceSummary:
    if window < 2:
        raise ValueError("window must be >= 2")

    event_types = tuple(_event_type(event) for event in events)
    if not event_types:
        return ConvergenceSummary(
            status="learning",
            window=window,
            event_count=0,
            structural_count=0,
            non_structural_count=0,
            recent_event_types=(),
            reason="no_experience_history",
        )

    recent = event_types[-window:]
    structural_count = sum(event_type in _STRUCTURAL for event_type in recent)
    non_structural_count = len(recent) - structural_count

    if _reopened_after_quiet_convergence(event_types, window):
        status: ExperienceConvergenceStatus = "reopened"
        reason = "structural_change_after_two_quiet_windows"
    elif (
        len(event_types) >= 2 * window
        and all(event_type not in _STRUCTURAL for event_type in event_types[-2 * window :])
    ):
        status = "converged"
        reason = "two_consecutive_quiet_windows"
    else:
        structural_threshold = max(2, ceil(len(recent) * 0.30))
        if structural_count >= structural_threshold:
            status = "learning"
            reason = "recent_window_contains_frequent_structural_change"
        elif non_structural_count > structural_count and len(recent) >= min(3, window):
            status = "converging"
            reason = "recent_window_is_dominated_by_state_optimization"
        else:
            status = "learning"
            reason = "insufficient_stable_history"

    return ConvergenceSummary(
        status=status,
        window=window,
        event_count=len(event_types),
        structural_count=structural_count,
        non_structural_count=non_structural_count,
        recent_event_types=recent,
        reason=reason,
    )


def _reopened_after_quiet_convergence(
    event_types: tuple[str, ...],
    window: int,
) -> bool:
    latest_window_start = max(0, len(event_types) - window)
    structural_indexes = [
        index
        for index in range(latest_window_start, len(event_types))
        if event_types[index] in _STRUCTURAL
    ]
    if not structural_indexes:
        return False

    first_recent_structural = structural_indexes[0]
    if first_recent_structural < 2 * window:
        return False

    prior = event_types[first_recent_structural - 2 * window : first_recent_structural]
    return all(event_type not in _STRUCTURAL for event_type in prior)


def _event_type(event) -> str:
    if isinstance(event, dict):
        value = event.get("event_type")
    else:
        value = getattr(event, "event_type", None)
    if not isinstance(value, str) or not value:
        raise ValueError("event must expose event_type")
    return value
