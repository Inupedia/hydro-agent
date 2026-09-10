"""Automatic calibration/development/final-holdout planning for product tasks.

The product receives one long historical record. This module detects observed flood
periods, groups them by water year, and chooses chronological disjoint windows so
roughly 80% of detected flood events remain visible to calibration/development while
roughly 20% stay sealed for the final test. The visible 80% is further split into
calibration and development windows; P2 uses the full continuous calibration window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

import numpy as np


@dataclass(frozen=True)
class ObservedFloodEvent:
    event_id: str
    start: date
    peak: date
    end: date
    water_year: int
    magnitude_class: str
    peak_discharge: float


@dataclass(frozen=True)
class DatasetWindow:
    start: date
    end: date


@dataclass(frozen=True)
class CalibrationDatasetPlan:
    calibration: DatasetWindow
    development: DatasetWindow
    final_holdout: DatasetWindow
    events: tuple[ObservedFloodEvent, ...]
    calibration_event_ids: tuple[str, ...]
    development_event_ids: tuple[str, ...]
    final_holdout_event_ids: tuple[str, ...]

    @property
    def visible_event_fraction(self) -> float:
        total = len(self.events)
        if not total:
            return 0.0
        return (len(self.calibration_event_ids) + len(self.development_event_ids)) / total


def water_year(day: date) -> int:
    """USGS-style water year: October-September, named for the ending year."""

    return day.year + (1 if day.month >= 10 else 0)


def _event_ranges(values: np.ndarray, *, quantile: float = 0.90, max_gap: int = 1):
    threshold = float(np.quantile(values, quantile))
    high = [i for i, value in enumerate(values) if value >= threshold]
    if not high:
        return []
    ranges: list[tuple[int, int]] = []
    start = previous = high[0]
    for index in high[1:]:
        if index - previous <= max_gap + 1:
            previous = index
            continue
        ranges.append((max(0, start - 1), min(len(values) - 1, previous + 2)))
        start = previous = index
    ranges.append((max(0, start - 1), min(len(values) - 1, previous + 2)))
    merged: list[tuple[int, int]] = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def detect_observed_flood_events(
    dated_flow: Iterable[tuple[date, float]],
    *,
    quantile: float = 0.90,
) -> tuple[ObservedFloodEvent, ...]:
    rows = sorted((day, float(value)) for day, value in dated_flow)
    if len(rows) < 30:
        raise ValueError("至少需要30天连续流量资料才能识别洪水事件")
    days = [row[0] for row in rows]
    values = np.asarray([row[1] for row in rows], dtype=float)
    ranges = _event_ranges(values, quantile=quantile)
    if not ranges:
        return ()
    peaks = [float(np.max(values[start : end + 1])) for start, end in ranges]
    p33, p67 = np.quantile(np.asarray(peaks, dtype=float), [0.33, 0.67])
    events = []
    for ordinal, (start, end) in enumerate(ranges, start=1):
        segment = values[start : end + 1]
        peak_local = int(np.argmax(segment))
        peak_index = start + peak_local
        peak_value = float(segment[peak_local])
        magnitude = "large" if peak_value >= p67 else "medium" if peak_value >= p33 else "small"
        events.append(
            ObservedFloodEvent(
                event_id=f"flood-{ordinal:03d}-{days[start].isoformat()}",
                start=days[start],
                peak=days[peak_index],
                end=days[end],
                water_year=water_year(days[peak_index]),
                magnitude_class=magnitude,
                peak_discharge=peak_value,
            )
        )
    return tuple(events)


def _event_share(events: tuple[ObservedFloodEvent, ...], start: date, end: date) -> float:
    if not events:
        return 0.0
    count = sum(start <= event.peak <= end for event in events)
    return count / len(events)


def _magnitude_penalty(
    events: tuple[ObservedFloodEvent, ...],
    start: date,
    end: date,
) -> float:
    selected = [event for event in events if start <= event.peak <= end]
    if not selected or not events:
        return 10.0
    total_dist = {
        name: sum(event.magnitude_class == name for event in events) / len(events)
        for name in ("small", "medium", "large")
    }
    selected_dist = {
        name: sum(event.magnitude_class == name for event in selected) / len(selected)
        for name in ("small", "medium", "large")
    }
    return sum(abs(selected_dist[name] - total_dist[name]) for name in total_dist)


def plan_calibration_dataset(
    dated_flow: Iterable[tuple[date, float]],
    *,
    record_start: date | None = None,
    record_end: date | None = None,
    target_final_fraction: float = 0.20,
) -> CalibrationDatasetPlan:
    rows = sorted((day, float(value)) for day, value in dated_flow)
    if not rows:
        raise ValueError("没有可用于率定的数据")
    start = max(rows[0][0], record_start) if record_start else rows[0][0]
    end = min(rows[-1][0], record_end) if record_end else rows[-1][0]
    scoped = [(day, value) for day, value in rows if start <= day <= end]
    events = detect_observed_flood_events(scoped)
    if len(events) < 6:
        raise ValueError("有效洪水事件少于6场，无法建立独立率定/开发/测试数据协议")

    years = sorted({water_year(day) for day, _ in scoped})
    if len(years) < 5:
        raise ValueError("至少需要5个水文年才能建立独立率定/开发/测试数据协议")

    # Keep the split chronological to eliminate event leakage across nearby floods.
    # Search water-year cut points and choose the combination that best approximates:
    # calibration ~64%, development ~16%, final sealed holdout ~20% of flood events.
    candidates = []
    for cal_year_count in range(2, len(years) - 2):
        for dev_year_count in range(1, len(years) - cal_year_count):
            final_year_count = len(years) - cal_year_count - dev_year_count
            if final_year_count < 1:
                continue
            cal_end_year = years[cal_year_count - 1]
            dev_end_year = years[cal_year_count + dev_year_count - 1]
            cal_end = date(cal_end_year, 9, 30)
            dev_start = date(cal_end_year, 10, 1)
            dev_end = date(dev_end_year, 9, 30)
            final_start = date(dev_end_year, 10, 1)
            cal_window_start = start
            final_window_end = end
            if not (cal_window_start <= cal_end < dev_start <= dev_end < final_start <= final_window_end):
                continue
            cal_share = _event_share(events, cal_window_start, cal_end)
            dev_share = _event_share(events, dev_start, dev_end)
            final_share = _event_share(events, final_start, final_window_end)
            if min(cal_share, dev_share, final_share) <= 0:
                continue
            score = (
                abs(final_share - target_final_fraction) * 5.0
                + abs((cal_share + dev_share) - (1.0 - target_final_fraction)) * 3.0
                + abs(dev_share - 0.16)
                + _magnitude_penalty(events, final_start, final_window_end)
            )
            candidates.append(
                (
                    score,
                    DatasetWindow(cal_window_start, cal_end),
                    DatasetWindow(dev_start, dev_end),
                    DatasetWindow(final_start, final_window_end),
                )
            )
    if not candidates:
        raise ValueError("无法从当前水文年与洪水事件分布构造互不重叠的数据协议")
    _, calibration, development, final_holdout = min(candidates, key=lambda item: item[0])

    def ids(window: DatasetWindow):
        return tuple(event.event_id for event in events if window.start <= event.peak <= window.end)

    return CalibrationDatasetPlan(
        calibration=calibration,
        development=development,
        final_holdout=final_holdout,
        events=events,
        calibration_event_ids=ids(calibration),
        development_event_ids=ids(development),
        final_holdout_event_ids=ids(final_holdout),
    )
