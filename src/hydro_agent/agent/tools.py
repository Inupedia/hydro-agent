from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Protocol

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.execution.hashing import sha256_bytes


class ToolUnavailable(LookupError):
    pass


class ToolHandler(Protocol):
    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket: ...


def _evidence_id() -> str:
    return f"ev-{uuid.uuid4().hex[:12]}"


def information_hash(
    *, action: ActionCode, status: str, observations: tuple[str, ...], metrics: dict
) -> str:
    payload = {
        "action": action.value,
        "status": status,
        "observations": list(observations),
        "metrics": metrics,
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class ToolRouter:
    def __init__(self):
        self._handlers: dict[ActionCode, ToolHandler] = {}

    def register(self, action: ActionCode, handler: ToolHandler) -> None:
        self._handlers[action] = handler

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        handler = self._handlers.get(decision.action)
        if handler is None:
            raise ToolUnavailable(f"no handler for {decision.action}")
        packet = handler.execute(task_id, decision)
        return packet


class CheckDataHandler:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        task = self.repository.get_task(task_id)
        state = self.repository.ensure_task_state(task_id)
        schemes = self.repository.list_schemes(task_id)
        snapshots = self.repository.list_snapshots(task_id=task_id)
        observations = (
            f"basin_id={task.basin_id}",
            f"scheme_count={len(schemes)}",
            f"current_scheme={state.current_scheme_id or 'none'}",
            f"snapshot_count={len(snapshots)}",
            f"latest_snapshot={snapshots[-1].snapshot_id if snapshots else 'none'}",
        )
        # Snapshots are built lazily; a configured scheme is enough to proceed.
        status = "succeeded" if schemes and state.current_scheme_id else "failed"
        metrics = {
            "scheme_count": float(len(schemes)),
            "snapshot_count": float(len(snapshots)),
        }
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A01_CHECK_DATA,
            status=status,
            observations=observations,
            metrics=metrics,
            new_information_hash=information_hash(
                action=ActionCode.A01_CHECK_DATA,
                status=status,
                observations=observations,
                metrics=metrics,
            ),
        )


class ValidateSchemeHandler:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        state = self.repository.ensure_task_state(task_id)
        scheme = self.repository.get_scheme(state.current_scheme_id)
        params = (scheme.config_json or {}).get("parameters") or {}
        ok = isinstance(params, dict) and bool(params)
        observations = (f"scheme_id={scheme.scheme_id}", f"parameter_count={len(params)}")
        status = "succeeded" if ok else "failed"
        metrics = {"parameter_count": float(len(params))}
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A03_VALIDATE_SCHEME,
            status=status,
            observations=observations,
            metrics=metrics,
            new_information_hash=information_hash(
                action=ActionCode.A03_VALIDATE_SCHEME,
                status=status,
                observations=observations,
                metrics=metrics,
            ),
        )


class DiagnoseHandler:
    """A06: evidence-grounded diagnosis using domain skills + forecast/obs errors."""

    def __init__(self, repository, *, diagnose_fn):
        self.repository = repository
        self.diagnose_fn = diagnose_fn

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        result = self.diagnose_fn(task_id)
        hypotheses = list(result.get("hypotheses") or [])
        hypothesis_lines = tuple(
            f"hypothesis[{index}]={item.get('id')}:{float(item.get('strength') or 0):.2f}:"
            f"{item.get('suggested_action')}:{item.get('suggested_strategy_id') or '-'}"
            for index, item in enumerate(hypotheses)
        )
        groups = result.get("recommended_param_groups")
        groups_text = ",".join(groups) if isinstance(groups, (list, tuple)) else ""
        observations = (
            f"phenomenon={result.get('phenomenon')}",
            f"hypothesis={result.get('hypothesis')}",
            f"recommended_action={result.get('recommended_action')}",
            f"recommended_strategy_id={result.get('recommended_strategy_id')}",
            f"recommended_param_groups={groups_text or '-'}",
            f"recommended_objective={result.get('recommended_objective') or '-'}",
            *hypothesis_lines,
            *(result.get("notes") or ()),
        )
        metrics = {
            str(k): float(v)
            for k, v in dict(result.get("metrics") or {}).items()
            if isinstance(v, (int, float))
        }
        gates = {
            "hypothesis": str(result.get("hypothesis") or "UNKNOWN"),
            "recommended_action": str(result.get("recommended_action") or ""),
            "recommended_strategy_id": str(result.get("recommended_strategy_id") or ""),
            "recommended_param_groups": groups_text,
            "recommended_objective": str(result.get("recommended_objective") or ""),
            "phenomenon": str(result.get("phenomenon") or ""),
            "skill_id": "forecast-diagnose",
            "hypotheses_json": json.dumps(hypotheses, ensure_ascii=False, sort_keys=True),
        }
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A06_DIAGNOSE,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            gates=gates,
            new_information_hash=information_hash(
                action=ActionCode.A06_DIAGNOSE,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


class ForecastHandler:
    def __init__(self, repository, *, forecast_service, issue_time: str, policy):
        self.repository = repository
        self.forecast_service = forecast_service
        self.issue_time = issue_time
        self.policy = policy

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        state = self.repository.ensure_task_state(task_id)
        record = self.forecast_service.forecast(
            task_id=task_id,
            scheme_id=state.current_scheme_id,
            issue_time=self.issue_time,
            policy=self.policy,
        )
        observations = (
            f"forecast_id={record.forecast_id}",
            f"leads={sorted(record.lead_values)}",
        )
        metrics = {f"lead_{k}": float(v) for k, v in sorted(record.lead_values.items())}
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action_run_id=record.action_run_id,
            action=ActionCode.A05_FORECAST,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            artifact_ids=tuple(record.artifact_ids),
            new_information_hash=information_hash(
                action=ActionCode.A05_FORECAST,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


class OptimizeHandler:
    def __init__(
        self,
        repository,
        *,
        calibration_service,
        candidate_service,
        calibration_snapshot_id: str,
        validation_snapshot_id: str,
        policy,
    ):
        self.repository = repository
        self.calibration_service = calibration_service
        self.candidate_service = candidate_service
        self.calibration_snapshot_id = calibration_snapshot_id
        self.validation_snapshot_id = validation_snapshot_id
        self.policy = policy

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        if decision.strategy_id == "xaj-hydrologist-manual-v1":
            observations = (
                "hydrologist_manual_required",
                "open_hydrologist_tune_ui",
                "strategy_id=xaj-hydrologist-manual-v1",
            )
            return EvidencePacket(
                evidence_id=_evidence_id(),
                task_id=task_id,
                action_run_id=None,
                action=ActionCode.A07_OPTIMIZE,
                status="blocked",
                observations=observations,
                metrics={},
                gates={
                    "strategy_id": "xaj-hydrologist-manual-v1",
                    "reason": "await_hydrologist_compare",
                },
                artifact_ids=(),
                new_information_hash=information_hash(
                    action=ActionCode.A07_OPTIMIZE,
                    status="blocked",
                    observations=observations,
                    metrics={},
                ),
            )
        state = self.repository.ensure_task_state(task_id)
        outcome = self.calibration_service.calibrate(
            task_id=task_id,
            base_scheme_id=state.current_scheme_id,
            calibration_snapshot_id=self.calibration_snapshot_id,
            validation_snapshot_id=self.validation_snapshot_id,
            strategy_id=decision.strategy_id,
            policy=self.policy,
            param_groups=decision.param_groups,
            objective=decision.objective,
        )
        base_params = dict(
            (self.repository.get_scheme(outcome.base_scheme_id).config_json or {}).get("parameters")
            or {}
        )
        delta = {
            key: float(outcome.candidate_parameters[key]) - float(base_params[key])
            for key in outcome.candidate_parameters
            if key in base_params
            and abs(float(outcome.candidate_parameters[key]) - float(base_params[key])) > 1e-12
        }
        groups_text = ",".join(outcome.param_groups)
        candidate_id = self.candidate_service.register_candidate(
            base_scheme_id=outcome.base_scheme_id,
            action_run_id=outcome.action_run_id,
            calibration_payload={
                "candidate_parameters": outcome.candidate_parameters,
                "strategy_id": outcome.strategy_id,
                "objective": outcome.objective,
                "param_groups": list(outcome.param_groups),
            },
        )
        observations = (
            f"candidate_scheme_id={candidate_id}",
            f"base_scheme_id={outcome.base_scheme_id}",
            f"strategy_id={outcome.strategy_id}",
            f"objective={outcome.objective}",
            f"param_groups={groups_text}",
            f"objective_value={outcome.objective_value}",
            f"parameter_delta={json.dumps(delta, sort_keys=True)}",
        )
        metrics = {"objective_value": float(outcome.objective_value)}
        payload = dict(outcome.result_payload or {})
        for prefix, blob in (
            ("baseline", payload.get("baseline_metrics")),
            ("candidate", payload.get("candidate_metrics")),
        ):
            if isinstance(blob, dict):
                for key in ("nse", "kge", "pbias_percent", "rmse_m3s"):
                    raw = blob.get(key)
                    if isinstance(raw, (int, float)):
                        metrics[f"{prefix}_{key}"] = float(raw)
        gates = {
            "candidate_scheme_id": candidate_id,
            "base_scheme_id": outcome.base_scheme_id,
            "strategy_id": str(outcome.strategy_id),
            "objective": outcome.objective,
            "param_groups": groups_text,
            "parameter_delta_json": json.dumps(delta, sort_keys=True),
        }
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action_run_id=outcome.action_run_id,
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            gates=gates,
            artifact_ids=tuple(outcome.artifact_ids),
            new_information_hash=information_hash(
                action=ActionCode.A07_OPTIMIZE,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


class GateHandler:
    def __init__(
        self,
        repository,
        *,
        gate_evaluator,
        policy,
        bundle_provider,
        gbt_config_provider=None,
    ):
        self.repository = repository
        self.gate_evaluator = gate_evaluator
        self.policy = policy
        self.bundle_provider = bundle_provider
        self.gbt_config_provider = gbt_config_provider

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        provided = self.bundle_provider(task_id)
        gbt_report = None
        if isinstance(provided, tuple) and len(provided) == 3:
            base, candidate, hydro_series = provided
            if hydro_series is not None and self.gbt_config_provider is not None:
                from hydro_agent.graphs.gbt_accuracy import run_gbt_accuracy

                gbt_report = run_gbt_accuracy(hydro_series, self.gbt_config_provider(task_id))
        else:
            base, candidate = provided
        result = self.gate_evaluator.evaluate(base, candidate, self.policy, gbt_report=gbt_report)
        observations = (
            f"gate_status={result.status}",
            f"base_scheme_id={result.base_scheme_id}",
            f"candidate_scheme_id={result.candidate_scheme_id}",
            f"base_primary={base.primary_score:.4f}",
            f"candidate_primary={candidate.primary_score:.4f}",
            f"min_candidate_primary={self.policy.min_candidate_primary:.4f}",
            f"min_scheme_grade={self.policy.min_scheme_grade}",
            *((f"scheme_grade={result.scheme_grade}",) if result.scheme_grade else ()),
            *((f"gbt_summary={result.gbt_summary}",) if result.gbt_summary else ()),
            *result.reasons,
        )
        metrics = {
            "primary_delta": float(result.primary_delta),
            "base_primary": float(base.primary_score),
            "candidate_primary": float(candidate.primary_score),
            "min_candidate_primary": float(self.policy.min_candidate_primary),
        }
        if gbt_report is not None:
            metrics.update(gbt_report.as_metrics_dict())
        gates = {
            "status": result.status,
            "base_scheme_id": result.base_scheme_id,
            "candidate_scheme_id": result.candidate_scheme_id,
            "reasons": ",".join(result.reasons),
            "scheme_grade": result.scheme_grade or "",
            "gbt_summary": result.gbt_summary or "",
        }
        if gbt_report is not None:
            gates["gbt_report_json"] = __import__("json").dumps(
                gbt_report.model_dump(), ensure_ascii=False, sort_keys=True
            )
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status=result.status,
            observations=observations,
            metrics=metrics,
            gates=gates,
            new_information_hash=information_hash(
                action=ActionCode.A08_GATE,
                status=result.status,
                observations=observations,
                metrics=metrics,
            ),
        )


class ResolveHandler:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        evidence = self.repository.list_evidence(task_id)
        gate = next(
            (row for row in reversed(evidence) if row.action == ActionCode.A08_GATE.value), None
        )
        status = "KEEP"
        if gate is not None:
            status = gate.gates_json.get("status", gate.status)
            if status == "ACCEPT":
                candidate_id = gate.gates_json.get("candidate_scheme_id")
                if candidate_id:
                    self.repository.update_task_state(task_id, current_scheme_id=candidate_id)
            elif status == "ROLLBACK":
                state = self.repository.get_task_state(task_id)
                self.repository.update_task_state(
                    task_id, current_scheme_id=state.current_scheme_id
                )
        observations = (f"resolve_status={status}",)
        metrics: dict[str, float] = {}
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A09_RESOLVE,
            status=status if status in ("KEEP", "ACCEPT", "ROLLBACK") else "succeeded",
            observations=observations,
            metrics=metrics,
            gates={"status": status},
            new_information_hash=information_hash(
                action=ActionCode.A09_RESOLVE,
                status=status,
                observations=observations,
                metrics=metrics,
            ),
        )


class FreezeToolHandler:
    def __init__(self, repository, *, freeze_service):
        self.repository = repository
        self.freeze_service = freeze_service

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        state = self.repository.ensure_task_state(task_id)
        frozen_id = self.freeze_service.freeze(
            task_id=task_id, source_scheme_id=state.current_scheme_id
        )
        self.repository.set_task_phase(task_id, "F")
        observations = (f"frozen_scheme_id={frozen_id}",)
        metrics: dict[str, float] = {}
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A10_FREEZE,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            new_information_hash=information_hash(
                action=ActionCode.A10_FREEZE,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


class ReplayToolHandler:
    def __init__(self, repository, *, planner, replay_service, start_date, end_date):
        self.repository = repository
        self.planner = planner
        self.replay_service = replay_service
        self.start_date = start_date
        self.end_date = end_date

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        plan = self.planner.plan(task_id, self.start_date, self.end_date)
        forecasts = self.replay_service.execute(plan)
        # Advance into read-only evaluation once historical replay succeeds.
        task = self.repository.get_task(task_id)
        if task.phase == "F":
            self.repository.set_task_phase(task_id, "E")
        observations = (
            f"forecast_count={len(forecasts)}",
            f"scheme_id={plan.scheme_id}",
        )
        metrics = {"forecast_count": float(len(forecasts))}
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A11_REPLAY,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            artifact_ids=tuple(f.forecast_id for f in forecasts),
            new_information_hash=information_hash(
                action=ActionCode.A11_REPLAY,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


class EvaluateReportToolHandler:
    def __init__(
        self,
        repository,
        *,
        evaluation_service,
        report_builder,
        observation_snapshot_id: str,
        output_dir,
    ):
        self.repository = repository
        self.evaluation_service = evaluation_service
        self.report_builder = report_builder
        self.observation_snapshot_id = observation_snapshot_id
        self.output_dir = output_dir

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        task = self.repository.get_task(task_id)
        if task.phase == "F":
            self.repository.set_task_phase(task_id, "E")
        evaluation = self.evaluation_service.evaluate(
            task_id, self.observation_snapshot_id, output_dir=self.output_dir
        )
        json_path, md_path = self.report_builder.build(evaluation, self.output_dir)
        artifacts = [json_path.name, md_path.name]
        for name in (
            "test-hydrograph.csv",
            "test-hydrograph.json",
            "test-hydrograph.png",
            "test-metrics.json",
        ):
            if (Path(self.output_dir) / name).is_file():
                artifacts.append(name)
        observations = (
            f"scheme_id={evaluation.scheme_id}",
            f"report_json={json_path.name}",
            f"report_md={md_path.name}",
        )
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action=ActionCode.A12_EVALUATE_REPORT,
            status="succeeded",
            observations=observations,
            metrics=dict(evaluation.metrics),
            artifact_ids=tuple(artifacts),
            new_information_hash=information_hash(
                action=ActionCode.A12_EVALUATE_REPORT,
                status="succeeded",
                observations=observations,
                metrics=dict(evaluation.metrics),
            ),
        )
