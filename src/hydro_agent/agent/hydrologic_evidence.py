"""Stable Skill/Agent-facing hydrologic evidence view.

Deterministic builders (``HydrologicEvidenceBundle``, calibration diagnostics)
remain the compute sources. Skills and orchestration should read this schema
instead of inventing metrics from raw arrays.
"""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import Field

from hydro_agent.evaluation.diagnosis_packet import HydrographDiagnosisPacket
from hydro_agent.execution.contracts import FrozenModel

ParameterGroup = tuple[str, ...]


class MetricSet(FrozenModel):
    nse: float | None = None
    kge: float | None = None
    pbias_percent: float | None = None
    rmse: float | None = None
    mae: float | None = None
    high_flow_mae: float | None = None
    extras: dict[str, float] = Field(default_factory=dict)


class FloodEventView(FrozenModel):
    event_id: str = ""
    peak_ratio: float | None = None
    peak_relative_error: float | None = None
    timing_lag_days: float | None = None
    timing_lag_steps: float | None = None
    volume_relative_error: float | None = None
    rising_limb_mae: float | None = None
    recession_mae: float | None = None
    basis: str | None = None
    start: str | None = None
    end: str | None = None
    status: str | None = None
    notes: tuple[str, ...] = ()


class DataQualityView(FrozenModel):
    coverage: float | None = None
    dropped_samples: int | None = None
    notes: tuple[str, ...] = ()


class HydrologicEvidence(FrozenModel):
    """Single language between Core facts and Skill reasoning."""

    phenomenon: str = ""
    hypothesis: str = "UNKNOWN"
    overall: MetricSet = Field(default_factory=MetricSet)
    high_flow: MetricSet = Field(default_factory=MetricSet)
    low_flow: MetricSet = Field(default_factory=MetricSet)
    flood_events: tuple[FloodEventView, ...] = ()
    diagnosis_packet: HydrographDiagnosisPacket | None = None
    water_balance: MetricSet = Field(default_factory=MetricSet)
    data_quality: DataQualityView = Field(default_factory=DataQualityView)
    recommended_action: str | None = None
    recommended_strategy_id: str | None = None
    recommended_param_groups: tuple[str, ...] = ()
    recommended_objective: str | None = None
    hypotheses: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()
    basin_attributes: dict[str, Any] = Field(default_factory=dict)
    previous_strategy_id: str | None = None
    local_boundary_hits: tuple[str, ...] = ()
    absolute_boundary_hits: tuple[str, ...] = ()
    contradictory_evidence_ids: tuple[str, ...] = ()
    # Preserve unknown diagnosis keys for gradual migration.
    extras: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_diagnosis(
        cls,
        diagnosis: Mapping[str, Any] | None,
        *,
        diagnosis_packet: HydrographDiagnosisPacket | None = None,
    ) -> HydrologicEvidence:
        raw = dict(diagnosis or {})
        legacy_metrics = (
            dict(raw.get("metrics") or {}) if isinstance(raw.get("metrics"), Mapping) else {}
        )
        metrics = dict(diagnosis_packet.overall.metrics) if diagnosis_packet else {}
        metrics.update(legacy_metrics)

        def _float(name: str, *aliases: str) -> float | None:
            for key in (name, *aliases):
                value = metrics.get(key)
                if value is None:
                    value = raw.get(key)
                try:
                    number = float(value)  # type: ignore[arg-type]
                except (TypeError, ValueError):
                    continue
                if number != number:  # NaN
                    continue
                return number
            return None

        known_metric_keys = {
            "nse",
            "kge",
            "pbias_percent",
            "pbias",
            "rmse",
            "mae",
            "high_flow_mae",
            "peak_ratio",
            "peak_timing_lag_days",
            "peak_timing_lag_leads",
        }
        extras_metrics = {
            str(key): float(value)
            for key, value in metrics.items()
            if key not in known_metric_keys and isinstance(value, (int, float))
        }
        overall = MetricSet(
            nse=_float("nse"),
            kge=_float("kge"),
            pbias_percent=_float("pbias_percent", "pbias"),
            rmse=_float("rmse"),
            mae=_float("mae"),
            high_flow_mae=_float("high_flow_mae"),
            extras=extras_metrics,
        )
        flood: list[FloodEventView] = []
        if diagnosis_packet is not None:
            for event in diagnosis_packet.flood_events:
                flood.append(
                    FloodEventView(
                        event_id=event.event_id,
                        peak_ratio=event.metrics.get("peak_ratio"),
                        peak_relative_error=event.metrics.get("peak_relative_error"),
                        timing_lag_steps=event.metrics.get("peak_timing_lag_steps"),
                        volume_relative_error=event.metrics.get("volume_relative_error"),
                        rising_limb_mae=event.metrics.get("rising_limb_mae"),
                        recession_mae=event.metrics.get("recession_mae"),
                        basis=event.basis,
                        start=event.start,
                        end=event.end,
                        status=event.status,
                        notes=event.notes,
                    )
                )
        else:
            peak_ratio = _float("peak_ratio")
            timing = _float("peak_timing_lag_days", "peak_timing_lag_leads")
            if peak_ratio is not None or timing is not None:
                flood.append(
                    FloodEventView(
                        event_id="diagnostic-peak",
                        peak_ratio=peak_ratio,
                        timing_lag_days=timing,
                    )
                )

        groups = raw.get("recommended_param_groups") or ()
        if isinstance(groups, str):
            group_tuple = tuple(item.strip() for item in groups.split(",") if item.strip())
        elif isinstance(groups, (list, tuple)):
            group_tuple = tuple(str(item).strip() for item in groups if str(item).strip())
        else:
            group_tuple = ()

        hypotheses_raw = raw.get("hypotheses") or ()
        hypotheses = tuple(item for item in hypotheses_raw if isinstance(item, dict))
        notes_raw = raw.get("notes") or ()
        notes = tuple(str(item) for item in notes_raw) if isinstance(notes_raw, (list, tuple)) else ()

        reserved = {
            "hypothesis",
            "phenomenon",
            "metrics",
            "recommended_action",
            "recommended_strategy_id",
            "recommended_param_groups",
            "recommended_objective",
            "hypotheses",
            "notes",
            "basin_attributes",
            "previous_strategy_id",
            "local_boundary_hits",
            "absolute_boundary_hits",
            "contradictory_evidence_ids",
        }
        extras = {str(k): v for k, v in raw.items() if k not in reserved}

        def _name_list(key: str) -> tuple[str, ...]:
            value = raw.get(key)
            if isinstance(value, str):
                return tuple(item.strip() for item in value.split(",") if item.strip())
            if isinstance(value, (list, tuple)):
                return tuple(str(item).strip() for item in value if str(item).strip())
            return ()

        basin = raw.get("basin_attributes")
        packet_high = diagnosis_packet.flow_regimes.get("high") if diagnosis_packet else None
        packet_low = diagnosis_packet.flow_regimes.get("low") if diagnosis_packet else None
        high = MetricSet(
            high_flow_mae=overall.high_flow_mae,
            mae=(
                packet_high.metrics.get("mae")
                if packet_high is not None
                else _float("high_flow_mae")
            ),
            extras=dict(packet_high.metrics) if packet_high is not None else {},
        )
        low = MetricSet(
            mae=packet_low.metrics.get("mae") if packet_low is not None else None,
            extras=dict(packet_low.metrics) if packet_low is not None else {},
        )
        water = MetricSet(
            pbias_percent=overall.pbias_percent,
            extras=(
                dict(diagnosis_packet.water_balance.metrics)
                if diagnosis_packet is not None
                else {}
            ),
        )
        data_quality = DataQualityView(
            coverage=diagnosis_packet.data_quality.coverage if diagnosis_packet else None,
            dropped_samples=(
                diagnosis_packet.data_quality.dropped_count if diagnosis_packet else None
            ),
            notes=(),
        )
        return cls(
            phenomenon=str(raw.get("phenomenon") or "").strip(),
            hypothesis=str(raw.get("hypothesis") or "UNKNOWN"),
            overall=overall,
            high_flow=high,
            low_flow=low,
            water_balance=water,
            flood_events=tuple(flood),
            diagnosis_packet=diagnosis_packet,
            data_quality=data_quality,
            recommended_action=str(raw["recommended_action"]) if raw.get("recommended_action") else None,
            recommended_strategy_id=(
                str(raw["recommended_strategy_id"]) if raw.get("recommended_strategy_id") else None
            ),
            recommended_param_groups=group_tuple,
            recommended_objective=(
                str(raw["recommended_objective"]) if raw.get("recommended_objective") else None
            ),
            hypotheses=hypotheses,
            notes=notes,
            basin_attributes=(
                dict(basin)
                if isinstance(basin, dict)
                else dict(diagnosis_packet.basin_attributes)
                if diagnosis_packet is not None
                else {}
            ),
            previous_strategy_id=(
                str(raw["previous_strategy_id"]) if raw.get("previous_strategy_id") else None
            ),
            local_boundary_hits=_name_list("local_boundary_hits"),
            absolute_boundary_hits=_name_list("absolute_boundary_hits"),
            contradictory_evidence_ids=_name_list("contradictory_evidence_ids"),
            extras=extras,
        )

    def as_diagnosis_dict(self) -> dict[str, Any]:
        """Compatibility projection for planners that still expect diagnosis dicts."""

        metrics: dict[str, float] = {}
        for key in ("nse", "kge", "pbias_percent", "rmse", "mae", "high_flow_mae"):
            value = getattr(self.overall, key)
            if value is not None:
                metrics[key] = float(value)
        metrics.update(self.overall.extras)
        if self.flood_events:
            first = self.flood_events[0]
            if first.peak_ratio is not None:
                metrics["peak_ratio"] = float(first.peak_ratio)
            if first.timing_lag_days is not None:
                metrics["peak_timing_lag_days"] = float(first.timing_lag_days)

        payload: dict[str, Any] = {
            "hypothesis": self.hypothesis,
            "phenomenon": self.phenomenon,
            "metrics": metrics,
            "notes": list(self.notes),
            "hypotheses": [dict(item) for item in self.hypotheses],
            "recommended_param_groups": list(self.recommended_param_groups),
            "local_boundary_hits": list(self.local_boundary_hits),
            "absolute_boundary_hits": list(self.absolute_boundary_hits),
            "contradictory_evidence_ids": list(self.contradictory_evidence_ids),
            **self.extras,
        }
        if self.recommended_action:
            payload["recommended_action"] = self.recommended_action
        if self.recommended_strategy_id:
            payload["recommended_strategy_id"] = self.recommended_strategy_id
        if self.recommended_objective:
            payload["recommended_objective"] = self.recommended_objective
        if self.basin_attributes:
            payload["basin_attributes"] = dict(self.basin_attributes)
        if self.previous_strategy_id:
            payload["previous_strategy_id"] = self.previous_strategy_id
        if self.diagnosis_packet is not None:
            payload["diagnosis_packet"] = self.diagnosis_packet.model_dump(mode="json")
        return payload

    def metric_lines(self, *, limit: int = 8) -> tuple[str, ...]:
        lines: list[str] = []
        for key in ("nse", "kge", "pbias_percent", "rmse", "mae", "high_flow_mae"):
            value = getattr(self.overall, key)
            if value is not None:
                lines.append(f"{key}={float(value):.6g}")
        for key, value in sorted(self.overall.extras.items()):
            lines.append(f"{key}={float(value):.6g}")
            if len(lines) >= limit:
                break
        return tuple(lines[:limit])
