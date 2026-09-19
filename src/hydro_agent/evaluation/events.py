from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal, Sequence

import numpy as np


@dataclass(frozen=True)
class EventSegmentationConfig:
    high_flow_quantile: float = 0.90
    min_event_steps: int = 3
    min_separation_steps: int = 2
    rise_search_steps: int = 3
    recession_search_steps: int = 5

    def __post_init__(self) -> None:
        if not 0.0 <= self.high_flow_quantile <= 1.0:
            raise ValueError("high_flow_quantile must be between 0 and 1")
        for field_name in (
            "min_event_steps",
            "min_separation_steps",
            "rise_search_steps",
            "recession_search_steps",
        ):
            if getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be non-negative")
        if self.min_event_steps < 1:
            raise ValueError("min_event_steps must be at least 1")


@dataclass(frozen=True)
class FloodEventBoundary:
    event_id: str
    start: date
    peak_time: date
    end: date
    basis: Literal["flow_only", "rainfall_runoff"]
    rain_start: date | None = None
    rain_end: date | None = None


def _finite_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _is_local_maximum(values: Sequence[float | None], index: int) -> bool:
    current = values[index]
    if current is None:
        return False

    left = values[index - 1] if index > 0 else None
    right = values[index + 1] if index + 1 < len(values) else None
    neighbours = [value for value in (left, right) if value is not None]
    if not neighbours:
        return False

    return all(current >= value for value in neighbours) and any(
        current > value for value in neighbours
    )


def _event_peak_index(
    observed: Sequence[float | None], start_index: int, end_index: int
) -> int:
    candidates = [
        (value, index)
        for index, value in enumerate(
            observed[start_index : end_index + 1], start=start_index
        )
        if value is not None
    ]
    if not candidates:
        raise ValueError("event window does not contain valid observed flow")
    peak_value = max(value for value, _ in candidates)
    return next(index for value, index in candidates if value == peak_value)


def segment_flood_events(
    *,
    dates: Sequence[date],
    observed: Sequence[float],
    precipitation: Sequence[float | None] | None = None,
    config: EventSegmentationConfig | None = None,
) -> tuple[FloodEventBoundary, ...]:
    config = config or EventSegmentationConfig()
    if len(dates) != len(observed):
        raise ValueError("dates and observed must have equal lengths")
    if precipitation is not None and len(precipitation) != len(dates):
        raise ValueError("precipitation must have the same length as dates")
    if any(current <= previous for previous, current in zip(dates, dates[1:])):
        raise ValueError("dates must be strictly increasing")
    if not dates:
        return ()

    observed_values = tuple(_finite_float(value) for value in observed)
    valid_observed = [value for value in observed_values if value is not None]
    if len(valid_observed) < config.min_event_steps:
        return ()

    threshold = float(np.quantile(valid_observed, config.high_flow_quantile))
    peaks = [
        index
        for index, value in enumerate(observed_values)
        if value is not None
        and value >= threshold
        and _is_local_maximum(observed_values, index)
    ]
    if not peaks:
        return ()

    windows = [
        [
            max(0, peak - config.rise_search_steps),
            min(len(dates) - 1, peak + config.recession_search_steps),
        ]
        for peak in peaks
    ]

    merged: list[list[int]] = []
    for start_index, end_index in windows:
        if not merged:
            merged.append([start_index, end_index])
            continue
        previous = merged[-1]
        gap_steps = start_index - previous[1] - 1
        if gap_steps < config.min_separation_steps:
            previous[1] = max(previous[1], end_index)
        else:
            merged.append([start_index, end_index])

    precipitation_values = (
        tuple(_finite_float(value) for value in precipitation)
        if precipitation is not None
        else None
    )

    events: list[FloodEventBoundary] = []
    for start_index, end_index in merged:
        if end_index - start_index + 1 < config.min_event_steps:
            continue
        peak_index = _event_peak_index(observed_values, start_index, end_index)

        basis: Literal["flow_only", "rainfall_runoff"] = "flow_only"
        rain_start = None
        rain_end = None
        if precipitation_values is not None:
            rain_indices = [
                index
                for index in range(start_index, end_index + 1)
                if precipitation_values[index] is not None
                and precipitation_values[index] > 0.0
            ]
            if rain_indices:
                basis = "rainfall_runoff"
                rain_start = dates[rain_indices[0]]
                rain_end = dates[rain_indices[-1]]

        events.append(
            FloodEventBoundary(
                event_id=f"event-{len(events) + 1:03d}",
                start=dates[start_index],
                peak_time=dates[peak_index],
                end=dates[end_index],
                basis=basis,
                rain_start=rain_start,
                rain_end=rain_end,
            )
        )

    return tuple(events)
