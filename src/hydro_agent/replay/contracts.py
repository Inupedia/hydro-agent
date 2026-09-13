from __future__ import annotations

from datetime import datetime
from typing import Literal

from hydro_agent.execution.contracts import FrozenModel, Identifier


class ReplayCase(FrozenModel):
    issue_time: datetime
    data_snapshot_id: Identifier


class ReplayPlan(FrozenModel):
    task_id: Identifier
    scheme_id: Identifier
    forcing_mode: Literal["R", "F"]
    cases: tuple[ReplayCase, ...]


class ReplayEvaluation(FrozenModel):
    task_id: Identifier
    scheme_id: Identifier
    observation_snapshot_id: Identifier
    forecast_ids: tuple[str, ...]
    # Compatibility aggregate: rolling forecast skill plus namespaced evidence.
    metrics: dict[str, float]
    # Rolling issue-date replay skill, including per-lead forecast metrics.
    rolling_metrics: dict[str, float] = {}
    lead_metrics: dict[str, dict[str, float]]
    # One uninterrupted frozen-scheme simulation across final_test.
    continuous_metrics: dict[str, float] = {}
    # Multi-scale evidence is derived from that same uninterrupted final-test
    # trajectory. Unsupported annual/seasonal/FDC sections remain explicitly
    # ``insufficient_data`` rather than being inferred from a short window.
    hydrologic_evidence: dict[str, object] = {}
    sample_counts: dict[str, int]
    forcing_mode: Literal["R", "F"]
    provenance: dict[str, object] = {}
    hydrograph: dict[str, object] | None = None
