from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from hydro_agent.agent.contracts import ActionCode
from hydro_agent.evaluation.evidence import HydrologicEvidenceBuilder
from hydro_agent.evaluation.metrics import build_evaluation_bundle
from hydro_agent.execution.contracts import ExecutionPolicy


@dataclass(frozen=True)
class ValidationWindow:
    start: date
    end: date

    @property
    def issue_days(self) -> tuple[date, ...]:
        days = []
        cur = self.start
        while cur <= self.end:
            days.append(cur)
            cur += timedelta(days=1)
        return tuple(days)

    @property
    def calibration_issue(self) -> date:
        return self.start - timedelta(days=1)

    def contains_target(self, target: date) -> bool:
        return self.start <= target <= self.end


def _eligible_for_scoring(row: Any) -> bool:
    return bool(getattr(row, "eligible_for_scoring", True))


def truth_from_source(flow_rows) -> dict[date, float]:
    """Return only observations that are explicitly eligible for formal scoring."""

    return {
        row.valid_date: float(row.discharge_m3s) for row in flow_rows if _eligible_for_scoring(row)
    }


def collect_lead_series(
    *,
    forecasts,
    scheme_id: str,
    truth: dict[date, float],
    window: ValidationWindow | None = None,
) -> dict[int, tuple[list[float], list[float]]]:
    lead_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    lead_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}
    for forecast in forecasts:
        if forecast.scheme_id != scheme_id:
            continue
        issue_date = forecast.issue_time.date()
        if window is not None and (issue_date < window.start or issue_date > window.end):
            continue
        values = forecast.lead_values_json
        for lead_key, value in values.items():
            lead = int(lead_key)
            if lead not in lead_obs:
                continue
            target = issue_date + timedelta(days=lead)
            # Independence is defined by the target truth date, not only by the
            # issue date. Never allow a development forecast to score against
            # final_test observations.
            if window is not None and not window.contains_target(target):
                continue
            if target not in truth:
                continue
            lead_obs[lead].append(float(truth[target]))
            lead_sim[lead].append(float(value))
    return {lead: (lead_obs[lead], lead_sim[lead]) for lead in (1, 2, 3)}


def collect_aligned_lead_series(
    *,
    forecasts,
    base_scheme_id: str,
    candidate_scheme_id: str,
    truth: dict[date, float],
    window: ValidationWindow,
) -> tuple[
    dict[int, tuple[list[float], list[float]]],
    dict[int, tuple[list[float], list[float]]],
]:
    """Build base/candidate series on identical legal development targets."""

    by_scheme_issue: dict[tuple[str, date], Any] = {}
    for forecast in forecasts:
        if forecast.scheme_id not in (base_scheme_id, candidate_scheme_id):
            continue
        issue_date = forecast.issue_time.date()
        if issue_date < window.start or issue_date > window.end:
            continue
        key = (forecast.scheme_id, issue_date)
        prev = by_scheme_issue.get(key)
        if prev is None or str(forecast.forecast_id) >= str(prev.forecast_id):
            by_scheme_issue[key] = forecast

    base_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    base_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}
    cand_obs: dict[int, list[float]] = {1: [], 2: [], 3: []}
    cand_sim: dict[int, list[float]] = {1: [], 2: [], 3: []}

    for day in window.issue_days:
        base_f = by_scheme_issue.get((base_scheme_id, day))
        cand_f = by_scheme_issue.get((candidate_scheme_id, day))
        if base_f is None or cand_f is None:
            continue
        for lead in (1, 2, 3):
            target = day + timedelta(days=lead)
            if not window.contains_target(target) or target not in truth:
                continue
            key = str(lead)
            if key not in base_f.lead_values_json or key not in cand_f.lead_values_json:
                continue
            obs = float(truth[target])
            base_obs[lead].append(obs)
            cand_obs[lead].append(obs)
            base_sim[lead].append(float(base_f.lead_values_json[key]))
            cand_sim[lead].append(float(cand_f.lead_values_json[key]))

    return (
        {lead: (base_obs[lead], base_sim[lead]) for lead in (1, 2, 3)},
        {lead: (cand_obs[lead], cand_sim[lead]) for lead in (1, 2, 3)},
    )


def require_enough_pairs(series: dict[int, tuple[list[float], list[float]]]) -> tuple[int, ...]:
    """Require at least one scoreable lead without borrowing out-of-window truth."""

    available = tuple(
        lead for lead, (obs, sim) in series.items() if len(obs) >= 2 and len(obs) == len(sim)
    )
    if not available:
        raise RuntimeError("development window has no lead with >=2 legal target pairs")
    return available


def resolve_gate_scheme_ids(repository, task_id: str) -> tuple[str, str]:
    state = repository.ensure_task_state(task_id)
    base_scheme_id = state.current_scheme_id
    if not base_scheme_id:
        raise RuntimeError("gate requires a current scheme")

    candidate_scheme_id: str | None = None
    optimize_base_id: str | None = None
    for row in reversed(repository.list_evidence(task_id)):
        if row.action != ActionCode.A05_OPTIMIZE.value:
            continue
        gates = dict(row.gates_json or {})
        candidate_scheme_id = gates.get("candidate_scheme_id") or None
        optimize_base_id = gates.get("base_scheme_id") or None
        if not candidate_scheme_id:
            for obs in row.observations_json or ():
                if str(obs).startswith("candidate_scheme_id="):
                    candidate_scheme_id = str(obs).split("=", 1)[1]
                    break
        break

    if not candidate_scheme_id:
        raise RuntimeError("gate requires a candidate from the latest A05_OPTIMIZE")

    if candidate_scheme_id == base_scheme_id:
        try:
            scheme = repository.get_scheme(candidate_scheme_id)
            provenance = dict((scheme.config_json or {}).get("provenance") or {})
            base_scheme_id = str(
                provenance.get("base_scheme_id") or optimize_base_id or base_scheme_id
            )
        except KeyError:
            if optimize_base_id:
                base_scheme_id = optimize_base_id

    if candidate_scheme_id == base_scheme_id:
        raise RuntimeError("gate candidate equals baseline scheme")
    return base_scheme_id, candidate_scheme_id


def behavioral_candidate_scheme_ids(
    repository,
    task_id: str,
    *,
    primary_candidate_id: str,
) -> tuple[str, ...]:
    """Return candidate schemes materialized by the latest A05 experiment."""

    values: list[str] = [str(primary_candidate_id)]
    for row in reversed(repository.list_evidence(task_id)):
        if row.action != ActionCode.A05_OPTIMIZE.value:
            continue
        gates = dict(row.gates_json or {})
        raw = gates.get("behavioral_candidate_scheme_ids_json")
        parsed: object = ()
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = tuple(item.strip() for item in raw.split(",") if item.strip())
        elif isinstance(raw, (list, tuple)):
            parsed = raw
        if isinstance(parsed, (list, tuple)):
            values.extend(str(item) for item in parsed if str(item))
        break
    return tuple(dict.fromkeys(values))


def _development_event_rows(
    series: dict[int, tuple[list[float], list[float]]],
    *,
    window: ValidationWindow,
) -> list[dict[str, float | str]]:
    observed, simulated = series.get(1, ([], []))
    if len(observed) < 2 or len(observed) != len(simulated):
        return []
    dates = tuple(window.start + timedelta(days=index) for index in range(len(observed)))
    try:
        evidence = HydrologicEvidenceBuilder(
            min_overall_samples=2,
            min_slice_samples=2,
            min_year_samples=2,
            min_fdc_samples=2,
            min_event_samples=2,
        ).build(
            window="development",
            dates=dates,
            observed=observed,
            simulated=simulated,
        )
    except ValueError:
        return []

    rows: list[dict[str, float | str]] = []
    for event in evidence.flood_events:
        metrics = event.metrics
        row: dict[str, float | str] = {"event_id": event.event_id}
        for source_key, output_key in (
            ("peak_relative_error", "peak_relative_error"),
            ("peak_timing_lag_steps", "timing_lag_steps"),
            ("volume_relative_error", "volume_relative_error"),
        ):
            value = metrics.get(source_key)
            if isinstance(value, (int, float)):
                row[output_key] = float(value)
        rows.append(row)
    return rows


def development_event_comparison(
    base_series: dict[int, tuple[list[float], list[float]]],
    candidate_series: dict[int, tuple[list[float], list[float]]],
    *,
    window: ValidationWindow,
) -> dict[str, object]:
    return {
        "base": _development_event_rows(base_series, window=window),
        "candidate": _development_event_rows(candidate_series, window=window),
    }


def latest_candidate_scheme_id(repository, task_id: str) -> str | None:
    for row in reversed(repository.list_evidence(task_id)):
        if row.action != ActionCode.A05_OPTIMIZE.value:
            continue
        gates = dict(row.gates_json or {})
        candidate = gates.get("candidate_scheme_id")
        if candidate:
            return str(candidate)
        for obs in row.observations_json or ():
            if str(obs).startswith("candidate_scheme_id="):
                return str(obs).split("=", 1)[1]
    return None


class RealValidationGate:
    """Score base/candidate using development targets only."""

    def __init__(
        self,
        *,
        repository,
        forecast_service,
        source,
        policy: ExecutionPolicy,
        task_configs: dict,
        research_policy=None,
    ):
        self.repository = repository
        self.forecast = forecast_service
        self.source = source
        self.policy = policy
        self.task_configs = task_configs
        self.research_policy = research_policy

    def window_for(self, task_id: str) -> ValidationWindow:
        cfg = self.task_configs.get(task_id) or {}
        start = cfg.get("development_start_date") or cfg.get("start_date") or "2020-04-29"
        end = cfg.get("development_end_date") or cfg.get("end_date") or "2020-05-01"
        start_d = date.fromisoformat(start[:10]) if isinstance(start, str) else start
        end_d = date.fromisoformat(end[:10]) if isinstance(end, str) else end
        return ValidationWindow(start=start_d, end=end_d)

    def ensure_forecasts(self, task_id: str, scheme_id: str, window: ValidationWindow) -> None:
        for day in window.issue_days:
            # Issues whose +1 target is already outside development cannot
            # contribute any legal Gate evidence and should not consume runtime.
            if not window.contains_target(day + timedelta(days=1)):
                continue
            issue = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            issue_iso = issue.isoformat().replace("+00:00", "Z")
            self.forecast.forecast(
                task_id=task_id,
                scheme_id=scheme_id,
                issue_time=issue_iso,
                policy=self.policy,
            )

    def bundles(self, task_id: str):
        base, candidate, hydro, _event_comparison = self.bundles_with_events(task_id)
        return base, candidate, hydro

    def bundles_with_events(self, task_id: str):
        base_scheme_id, primary_candidate_id = resolve_gate_scheme_ids(
            self.repository, task_id
        )
        candidate_ids = behavioral_candidate_scheme_ids(
            self.repository,
            task_id,
            primary_candidate_id=primary_candidate_id,
        )
        window = self.window_for(task_id)
        self.ensure_forecasts(task_id, base_scheme_id, window)
        for candidate_id in candidate_ids:
            self.ensure_forecasts(task_id, candidate_id, window)

        truth = truth_from_source(self.source.flow_rows)
        forecasts = self.repository.list_forecasts(task_id)
        comparisons: list[tuple[object, object, dict[int, tuple[list[float], list[float]]], dict[int, tuple[list[float], list[float]]], dict[str, object]]] = []
        for candidate_id in candidate_ids:
            base_series, cand_series = collect_aligned_lead_series(
                forecasts=forecasts,
                base_scheme_id=base_scheme_id,
                candidate_scheme_id=candidate_id,
                truth=truth,
                window=window,
            )
            base_available = require_enough_pairs(base_series)
            cand_available = require_enough_pairs(cand_series)
            if base_available != cand_available:
                raise RuntimeError(
                    "development Gate base/candidate availability mismatch"
                )
            base_bundle = build_evaluation_bundle(base_scheme_id, base_series)
            candidate_bundle = build_evaluation_bundle(candidate_id, cand_series)
            event_comparison = development_event_comparison(
                base_series,
                cand_series,
                window=window,
            )
            comparisons.append(
                (
                    base_bundle,
                    candidate_bundle,
                    base_series,
                    cand_series,
                    event_comparison,
                )
            )

        if not comparisons:
            raise RuntimeError("development Gate has no behavioral candidate evidence")

        selected = None
        if self.research_policy is not None:
            from hydro_agent.optimization.gate import ResearchGateEvaluator

            accepted = []
            for item in comparisons:
                research = ResearchGateEvaluator().evaluate(
                    item[0],
                    item[1],
                    self.research_policy,
                    event_comparison=item[4],
                )
                if (
                    research.adoption_status == "ADOPT"
                    and research.research_qualification == "QUALIFIED"
                ):
                    accepted.append(item)
            if accepted:
                selected = max(
                    accepted,
                    key=lambda item: (
                        float(item[1].primary_score),
                        str(item[1].scheme_id),
                    ),
                )

        if selected is None:
            selected = max(
                comparisons,
                key=lambda item: (
                    float(item[1].primary_score),
                    str(item[1].scheme_id),
                ),
            )

        base_bundle, candidate_bundle, _base_series, cand_series, event_comparison = selected

        from hydro_agent.evaluation.gbt22482 import series_from_lead_lists

        area = None
        scheme = self.repository.get_scheme(candidate_bundle.scheme_id)
        cfg = dict(scheme.config_json or {})
        for key in ("area_km2", "basin_area_km2"):
            if cfg.get(key) is not None:
                try:
                    area = float(cfg[key])
                except (TypeError, ValueError):
                    pass
        hydro = series_from_lead_lists(cand_series, area_km2=area)
        return (
            base_bundle,
            candidate_bundle,
            hydro,
            event_comparison,
        )
