"""Strict normalizers; source units are explicit rather than inferred from column names."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .contracts import FlowObservation, ForcingRow


@dataclass(frozen=True)
class NormalizedCaravanRow:
    forcing: ForcingRow
    flow: FlowObservation | None


@dataclass(frozen=True)
class NormalizedSource:
    forcing_rows: tuple[ForcingRow, ...]
    flow_rows: tuple[FlowObservation, ...]
    basin: dict[str, object]
    metadata: dict[str, object] = field(default_factory=dict)


def normalize_caravan_row(row, *, area_km2, available_at, streamflow_unit):
    if area_km2 <= 0 or streamflow_unit not in ("mm/day", "m3/s"):
        raise ValueError("positive basin area and explicit streamflow unit required")
    forcing = ForcingRow(
        valid_date=date.fromisoformat(row["date"]),
        precipitation_mm_day=float(row["total_precipitation_sum"]),
        pet_mm_day=float(row["potential_evaporation_sum_FAO_PENMAN_MONTEITH"]),
        source_kind="reanalysis",
        source="caravan-era5-land-fao-pm",
        available_at=available_at,
    )
    raw = row.get("streamflow", "")
    flow = None
    if raw not in ("", "NaN", "nan"):
        value = float(raw)
        if streamflow_unit == "mm/day":
            value *= area_km2 * 1000 / 86400
        flow = FlowObservation(
            valid_date=forcing.valid_date,
            discharge_m3s=value,
            source="caravan-streamflow",
            available_at=available_at,
        )
    return NormalizedCaravanRow(forcing, flow)


def _imputation_metadata(root: Path) -> dict[str, dict]:
    path = root / "flow_imputations.jsonl"
    if not path.is_file():
        return {}
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        valid_date = str(payload.get("valid_date") or "")
        if valid_date:
            rows[valid_date] = payload
    return rows


def _flow_observation_from_json(line: str) -> FlowObservation:
    """Load one flow row without turning absent legacy metadata into invalid nulls.

    Product builders preserve explicit quality/source fields when the upstream
    source provides them. Older normalized packages may have no quality code at
    all (or an intermediate CSV may serialize that absence as JSON null). In
    that case the FlowObservation contract's historical default applies. An
    explicit non-empty quality value is never rewritten here.
    """

    payload = json.loads(line)
    if payload.get("quality_code") is None:
        payload.pop("quality_code", None)
    if payload.get("quality_note") is None:
        payload.pop("quality_note", None)
    return FlowObservation.model_validate(payload)


def load_normalized_source(path: Path) -> NormalizedSource:
    root = path.resolve()
    forcing = tuple(
        ForcingRow.model_validate_json(line)
        for line in (root / "forcing.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    imputed = _imputation_metadata(root)
    flow_rows: list[FlowObservation] = []
    for line in (root / "flow.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        observation = _flow_observation_from_json(line)
        quality = imputed.get(observation.valid_date.isoformat())
        if quality is not None:
            observation = observation.model_copy(
                update={
                    "eligible_for_scoring": False,
                    "quality_code": "imputed",
                    "quality_note": str(
                        quality.get("risk")
                        or quality.get("method")
                        or "imputed observation excluded from formal scoring"
                    ),
                }
            )
        flow_rows.append(observation)
    flow = tuple(flow_rows)
    basin = json.loads((root / "basin.json").read_text(encoding="utf-8"))
    meta_path = root / "basin_meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    if not forcing:
        raise ValueError("forcing.jsonl is empty")
    return NormalizedSource(forcing, flow, basin, metadata)
