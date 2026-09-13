"""Rebuild calibration trials from the append-only Evidence table.

No second database state is introduced.  A07/A08/A09 evidence rows remain the
source of truth and the Trial Ledger is a deterministic research view over those
facts.  This makes old tasks auditable without a schema migration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from hydro_agent.agent.contracts import ActionCode
from hydro_agent.optimization.experiments import TrialLedger, TrialRecord, infer_trial_outcome


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evidence_id(row: object) -> str:
    return str(getattr(row, "evidence_id", "") or "")


def _action(row: object) -> str:
    return str(getattr(row, "action", "") or "")


def _gates(row: object) -> dict[str, Any]:
    value = getattr(row, "gates_json", None)
    if value is None:
        value = getattr(row, "gates", None)
    return _dict(value)


def _metrics(row: object) -> dict[str, Any]:
    value = getattr(row, "metrics_json", None)
    if value is None:
        value = getattr(row, "metrics", None)
    return _dict(value)


def _tokens(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, (tuple, list, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _stable_signature(gates: dict[str, Any]) -> str:
    payload = {
        "strategy_id": str(gates.get("strategy_id") or ""),
        "objective": str(gates.get("objective_metric") or gates.get("objective") or ""),
        "param_groups": str(gates.get("param_groups") or ""),
        "evaluation_budget": str(gates.get("evaluation_budget") or ""),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _plan_id(a07_id: str, signature: str) -> str:
    digest = hashlib.sha256(f"{a07_id}|{signature}".encode()).hexdigest()[:16]
    return f"plan-{digest}"


class TrialLedgerBuilder:
    """Convert persisted A06→A07→A08→A09 cycles into structured trial records."""

    def build(self, rows: Sequence[object]) -> TrialLedger:
        ledger = TrialLedger()
        latest_diagnosis_id: str | None = None
        current: dict[str, Any] | None = None

        def flush() -> None:
            nonlocal current
            if current is None:
                return
            a07 = current["a07"]
            gates = _gates(a07)
            gate_row = current.get("a08")
            resolve_row = current.get("a09")
            gate_gates = _gates(gate_row) if gate_row is not None else {}
            resolve_gates = _gates(resolve_row) if resolve_row is not None else {}
            gate_metrics = _metrics(gate_row) if gate_row is not None else {}

            adoption = str(
                resolve_gates.get("adoption_status")
                or gate_gates.get("adoption_status")
                or "NOT_EVALUATED"
            )
            qualification = str(
                resolve_gates.get("qualification_status")
                or gate_gates.get("qualification_status")
                or "NOT_EVALUATED"
            )
            gate_status = str(
                resolve_gates.get("gate_status")
                or gate_gates.get("status")
                or getattr(gate_row, "status", "NOT_EVALUATED")
            )
            primary_delta_raw = gate_metrics.get("primary_delta")
            try:
                primary_delta = float(primary_delta_raw) if primary_delta_raw is not None else None
            except (TypeError, ValueError):
                primary_delta = None
            metric_deltas = {
                str(key): float(value)
                for key, value in gate_metrics.items()
                if key.endswith("delta") and isinstance(value, (int, float))
            }

            a07_id = _evidence_id(a07)
            signature = str(gates.get("experiment_signature") or "") or _stable_signature(gates)
            explicit_plan_id = str(gates.get("experiment_plan_id") or "")
            plan_id = explicit_plan_id or _plan_id(a07_id, signature)
            planned_refs = _tokens(gates.get("experiment_evidence_refs"))
            refs = tuple(
                dict.fromkeys(
                    (
                        *planned_refs,
                        *((current.get("diagnosis_id"),) if current.get("diagnosis_id") else ()),
                        *((a07_id,) if a07_id else ()),
                        *(
                            (_evidence_id(gate_row),)
                            if gate_row is not None and _evidence_id(gate_row)
                            else ()
                        ),
                        *(
                            (_evidence_id(resolve_row),)
                            if resolve_row is not None and _evidence_id(resolve_row)
                            else ()
                        ),
                    )
                )
            )
            model_evaluations_raw = gates.get("model_evaluations") or _metrics(a07).get(
                "model_evaluations", 0
            )
            try:
                model_evaluations = max(0, int(float(model_evaluations_raw)))
            except (TypeError, ValueError):
                model_evaluations = 0

            reason_codes = list(_tokens(gates.get("experiment_reason_codes")))
            if gate_row is not None:
                reason_codes.append("development_gate_recorded")
            if resolve_row is not None:
                reason_codes.append("resolve_recorded")

            ledger.append(
                TrialRecord(
                    trial_id=f"trial-{a07_id}" if a07_id else f"trial-{signature}",
                    plan_id=plan_id,
                    experiment_signature=signature,
                    strategy_id=str(gates.get("strategy_id") or "unknown"),
                    base_scheme_id=str(gates.get("base_scheme_id") or "") or None,
                    candidate_scheme_id=str(gates.get("candidate_scheme_id") or "") or None,
                    action_run_id=str(getattr(a07, "action_run_id", "") or "") or None,
                    model_evaluations=model_evaluations,
                    development_gate=gate_status,
                    adoption_status=adoption,
                    qualification_status=qualification,
                    metric_deltas=metric_deltas,
                    evidence_refs=refs,
                    hypothesis_outcome=infer_trial_outcome(
                        adoption_status=adoption,
                        qualification_status=qualification,
                        primary_delta=primary_delta,
                    ),
                    reason_codes=tuple(dict.fromkeys(reason_codes)),
                )
            )
            current = None

        for row in rows:
            action = _action(row)
            if action == ActionCode.A06_DIAGNOSE.value:
                latest_diagnosis_id = _evidence_id(row) or latest_diagnosis_id
                continue
            if action == ActionCode.A07_OPTIMIZE.value:
                flush()
                current = {"a07": row, "diagnosis_id": latest_diagnosis_id}
                continue
            if current is None:
                continue
            if action == ActionCode.A08_GATE.value and current.get("a08") is None:
                current["a08"] = row
            elif action == ActionCode.A09_RESOLVE.value and current.get("a09") is None:
                current["a09"] = row
                flush()

        flush()
        return ledger
