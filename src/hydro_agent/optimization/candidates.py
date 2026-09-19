from __future__ import annotations

import copy
import json
import math
from typing import Any

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel
from hydro_agent.execution.hashing import sha256_bytes


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )





class BehavioralCandidate(FrozenModel):
    candidate_id: str
    parameters: dict[str, float]
    objective_value: float
    process_evidence: dict[str, Any] = Field(default_factory=dict)
    parameter_distance_from_best: float = Field(ge=0.0)


class BehavioralCandidateSet(FrozenModel):
    objective_name: str
    objective_best: float
    objective_tolerance: float = Field(ge=0.0)
    items: tuple[BehavioralCandidate, ...]


def _normalized_parameter_distance(
    left: dict[str, float],
    right: dict[str, float],
    bounds: dict[str, tuple[float, float]] | None,
) -> float:
    names = tuple(sorted(set(left) & set(right)))
    if not names:
        return float("inf")
    squares: list[float] = []
    for name in names:
        if bounds is not None and name in bounds:
            low, high = bounds[name]
            scale = max(float(high) - float(low), 1e-12)
        else:
            scale = max(abs(float(left[name])), abs(float(right[name])), 1.0)
        squares.append(((float(left[name]) - float(right[name])) / scale) ** 2)
    return math.sqrt(sum(squares) / len(squares))


def behavioral_candidate_id(parameters: dict[str, float]) -> str:
    digest = sha256_bytes(canonical_json(parameters).encode("utf-8"))
    return f"behavior-{digest[:12]}"


def select_behavioral_candidates(
    *,
    candidates: list[dict[str, Any]],
    objective_name: str,
    parameter_bounds: dict[str, tuple[float, float]] | None = None,
    max_candidates: int = 8,
    objective_tolerance: float = 0.02,
    min_parameter_distance: float = 0.05,
) -> BehavioralCandidateSet:
    """Retain near-optimal, parameter-distinct calibration behaviors.

    Selection only reads calibration-window candidate records. It maximizes the
    existing numerical objective but does not collapse process evidence into a
    new composite score.
    """

    if max_candidates < 1:
        raise ValueError("max_candidates must be >= 1")
    if objective_tolerance < 0 or min_parameter_distance < 0:
        raise ValueError("candidate tolerances must be non-negative")

    normalized: list[tuple[str, float, dict[str, float], dict[str, Any]]] = []
    for raw in candidates:
        score_raw = raw.get("objective_value", raw.get("score"))
        params_raw = raw.get("parameters", raw.get("params"))
        if not isinstance(score_raw, (int, float)) or not math.isfinite(float(score_raw)):
            continue
        if not isinstance(params_raw, dict) or not params_raw:
            continue
        params = {str(name): float(value) for name, value in params_raw.items()}
        candidate_id = str(raw.get("candidate_id") or behavioral_candidate_id(params))
        evidence = raw.get("process_evidence")
        normalized.append(
            (
                candidate_id,
                float(score_raw),
                params,
                dict(evidence) if isinstance(evidence, dict) else {},
            )
        )
    if not normalized:
        raise ValueError("behavioral candidate selection requires a finite candidate")

    normalized.sort(key=lambda row: (-row[1], row[0]))
    best_id, best_score, best_params, best_evidence = normalized[0]
    kept: list[BehavioralCandidate] = [
        BehavioralCandidate(
            candidate_id=best_id,
            parameters=best_params,
            objective_value=best_score,
            process_evidence=best_evidence,
            parameter_distance_from_best=0.0,
        )
    ]
    for candidate_id, score, params, evidence in normalized[1:]:
        if best_score - score > objective_tolerance + 1e-12:
            continue
        if any(
            _normalized_parameter_distance(params, item.parameters, parameter_bounds)
            < min_parameter_distance
            for item in kept
        ):
            continue
        kept.append(
            BehavioralCandidate(
                candidate_id=candidate_id,
                parameters=params,
                objective_value=score,
                process_evidence=evidence,
                parameter_distance_from_best=_normalized_parameter_distance(
                    params, best_params, parameter_bounds
                ),
            )
        )
        if len(kept) >= max_candidates:
            break

    return BehavioralCandidateSet(
        objective_name=str(objective_name),
        objective_best=best_score,
        objective_tolerance=float(objective_tolerance),
        items=tuple(kept),
    )


class CandidateSchemeService:
    def __init__(self, repository):
        self.repository = repository

    def register_candidate(
        self, *, base_scheme_id: str, action_run_id: str, calibration_payload: dict
    ) -> str:
        base = self.repository.get_scheme(base_scheme_id)
        parameters = calibration_payload.get("candidate_parameters")
        strategy_id = calibration_payload.get("strategy_id")
        if not isinstance(parameters, dict) or not strategy_id:
            raise ValueError("invalid calibration payload")
        config = copy.deepcopy(base.config_json)
        config["parameters"] = {str(k): float(v) for k, v in parameters.items()}
        if calibration_payload.get("model_version"):
            config["model_version"] = calibration_payload["model_version"]
        config["provenance"] = {
            "model_source_sha256": calibration_payload.get("model_source_sha256"),
            "base_scheme_id": base_scheme_id,
            "created_by_action_run_id": action_run_id,
            "strategy_id": strategy_id,
            "objective": calibration_payload.get("objective"),
            "param_groups": calibration_payload.get("param_groups"),
            "search_boundary_evidence": calibration_payload.get("search_boundary_evidence"),
            "behavioral_candidates": calibration_payload.get("behavioral_candidates"),
        }
        short_run = action_run_id.replace("run-", "")[-12:]
        # Keep scheme ids short: Identifier max length is 128.
        scheme_id = f"{base.task_id}--cand-{short_run}"
        content_hash = sha256_bytes(canonical_json(config).encode("utf-8"))
        self.repository.create_scheme(
            scheme_id=scheme_id,
            task_id=base.task_id,
            model_id=base.model_id,
            status="candidate",
            config=config,
            content_hash=content_hash,
        )
        return scheme_id
