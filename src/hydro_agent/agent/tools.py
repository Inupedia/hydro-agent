from __future__ import annotations

import json
import uuid
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
        snapshots = self.repository.list_snapshots(task_id=task_id)
        observations = (
            f"snapshot_count={len(snapshots)}",
            f"latest={snapshots[-1].snapshot_id if snapshots else 'none'}",
        )
        status = "succeeded" if snapshots else "failed"
        metrics = {"snapshot_count": float(len(snapshots))}
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
        state = self.repository.ensure_task_state(task_id)
        outcome = self.calibration_service.calibrate(
            task_id=task_id,
            base_scheme_id=state.current_scheme_id,
            calibration_snapshot_id=self.calibration_snapshot_id,
            validation_snapshot_id=self.validation_snapshot_id,
            strategy_id=decision.strategy_id,
            policy=self.policy,
        )
        candidate_id = self.candidate_service.register_candidate(
            base_scheme_id=outcome.base_scheme_id,
            action_run_id=outcome.action_run_id,
            calibration_payload={
                "candidate_parameters": outcome.candidate_parameters,
                "strategy_id": outcome.strategy_id,
            },
        )
        observations = (
            f"candidate_scheme_id={candidate_id}",
            f"strategy_id={outcome.strategy_id}",
            f"objective_value={outcome.objective_value}",
        )
        metrics = {"objective_value": float(outcome.objective_value)}
        return EvidencePacket(
            evidence_id=_evidence_id(),
            task_id=task_id,
            action_run_id=outcome.action_run_id,
            action=ActionCode.A07_OPTIMIZE,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            artifact_ids=tuple(outcome.artifact_ids),
            new_information_hash=information_hash(
                action=ActionCode.A07_OPTIMIZE,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


class GateHandler:
    def __init__(self, repository, *, gate_evaluator, policy, bundle_provider):
        self.repository = repository
        self.gate_evaluator = gate_evaluator
        self.policy = policy
        self.bundle_provider = bundle_provider

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        base, candidate = self.bundle_provider(task_id)
        result = self.gate_evaluator.evaluate(base, candidate, self.policy)
        observations = (f"gate_status={result.status}", *result.reasons)
        metrics = {"primary_delta": float(result.primary_delta)}
        gates = {"status": result.status, "candidate_scheme_id": result.candidate_scheme_id}
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
