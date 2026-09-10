from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.agent.tools import OptimizeHandler, information_hash
from hydro_agent.calibration.contracts import CalibrationPhase, PhaseGateStatus, SearchProgressPoint
from hydro_agent.calibration.development import infer_rework_phase
from hydro_agent.calibration.identity import calibration_experiment_id, development_validation_id
from hydro_agent.graphs.gbt_accuracy import run_gbt_accuracy
from hydro_agent.workbench.real import POLICY


class PhaseOptimizeHandler:
    _DEFAULTS = {
        CalibrationPhase.WATER_BALANCE: (("evap", "runoff"), "water_balance"),
        CalibrationPhase.SOURCE_RECESSION: (("runoff", "routing"), "recession"),
        CalibrationPhase.ROUTING_EVENT: (("runoff", "routing"), "routing_event"),
        CalibrationPhase.JOINT_REFINE: (("evap", "runoff", "routing"), "joint"),
    }

    def __init__(self, kernel):
        self.kernel = kernel

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        evidence = self.kernel.repository.list_evidence(task_id)
        phase = self.kernel.protocol.phase_from_evidence(evidence)
        if phase not in self._DEFAULTS:
            raise RuntimeError(f"optimization forbidden in calibration phase {phase.value}")
        default_groups, objective = self._DEFAULTS[phase]
        selected_groups = tuple(
            g for g in (decision.param_groups or default_groups) if g in set(default_groups)
        ) or default_groups

        plan = self.kernel.evaluator.plan_for(task_id)
        cal = plan.calibration
        warmup = int(self.kernel.scheme_template["warmup_days"])
        cal_days = (cal.end - cal.start).days + 1
        cal_issue = datetime.combine(cal.end + timedelta(days=1), datetime.min.time(), timezone.utc)
        cal_id = self.kernel.resolver.resolve(
            task_id,
            "calibrate",
            cal_issue.isoformat().replace("+00:00", "Z"),
            history_days=warmup + cal_days + 1,
        )
        patched = AgentDecision(
            action=ActionCode.A07_OPTIMIZE,
            hypothesis=decision.hypothesis,
            strategy_id=decision.strategy_id or "xaj-bounded-v1",
            param_groups=selected_groups,  # type: ignore[arg-type]
            objective=objective,  # type: ignore[arg-type]
            rationale_summary=decision.rationale_summary,
        )
        packet = OptimizeHandler(
            self.kernel.repository,
            calibration_service=self.kernel.calibration,
            candidate_service=self.kernel.candidates,
            calibration_snapshot_id=cal_id,
            # The runtime contract still accepts a validation snapshot, but phase search
            # must not see the development period. Reuse the calibration snapshot here.
            validation_snapshot_id=cal_id,
            policy=POLICY,
        ).execute(task_id, patched)
        candidate_id = str(packet.gates.get("candidate_scheme_id") or "")
        optimizer_run_id = str(packet.action_run_id or packet.evidence_id)
        experiment_id = calibration_experiment_id(
            optimizer_run_id,
            candidate_id,
            cal.start,
            cal.end,
        )
        gates = {
            **dict(packet.gates),
            "calibration_phase": phase.value,
            "experiment_id": experiment_id,
            "optimizer_action_run_id": optimizer_run_id,
            "phase_gate_window": f"{cal.start}..{cal.end}",
            "objective": objective,
        }
        observations = tuple(packet.observations) + (
            f"calibration_phase={phase.value}",
            f"phase_objective={objective}",
            f"experiment_id={experiment_id}",
            f"optimizer_action_run_id={optimizer_run_id}",
            f"calibration_window={cal.start}..{cal.end}",
            "development_visible=false",
            "final_holdout_visible=false",
        )
        return packet.model_copy(update={"gates": gates, "observations": observations})


class HydrologicGateHandler:
    def __init__(self, kernel):
        self.kernel = kernel

    @staticmethod
    def _forcing_warning(evidence) -> bool:
        for row in reversed(evidence):
            if row.action != ActionCode.A06_DIAGNOSE.value:
                continue
            try:
                return float((row.metrics_json or {}).get("forcing_adequacy_warning", 0.0)) >= 0.5
            except (TypeError, ValueError):
                return False
        return False

    @staticmethod
    def _history(evidence, phase: CalibrationPhase) -> tuple[SearchProgressPoint, ...]:
        points: list[SearchProgressPoint] = []
        seen: set[str] = set()
        for row in evidence:
            if row.action != ActionCode.A08_GATE.value:
                continue
            gates = dict(row.gates_json or {})
            if gates.get("calibration_phase") != phase.value:
                continue
            experiment_id = str(gates.get("experiment_id") or "")
            if not experiment_id or experiment_id in seen:
                continue
            seen.add(experiment_id)
            metrics = dict(row.metrics_json or {})
            if "phase_progress_value" not in metrics:
                continue
            points.append(
                SearchProgressPoint(
                    experiment_id=experiment_id,
                    phase=phase,
                    value=float(metrics["phase_progress_value"]),
                    higher_is_better=str(gates.get("higher_is_better") or "true").lower() == "true",
                )
            )
        return tuple(points)

    def _development_gate(self, task_id: str, evidence, phase: CalibrationPhase):
        repo = self.kernel.repository
        plan = self.kernel.evaluator.plan_for(task_id)
        dev = plan.development
        state = repo.get_task_state(task_id)
        scheme_id = state.current_scheme_id
        hydro, signatures = self.kernel.evaluator.evaluate_scheme(scheme_id, dev)
        gbt = run_gbt_accuracy(
            hydro,
            self.kernel.skills.gbt_accuracy_config(
                area_km2=float(self.kernel.source.basin.get("area_km2") or 0.0)
            ),
        )
        experiment_id = development_validation_id(scheme_id, dev.start, dev.end)
        assessment = self.kernel.phase_gate.evaluate(
            phase=phase,
            base_scheme_id=scheme_id,
            candidate_scheme_id=scheme_id,
            experiment_id=experiment_id,
            base_metrics=signatures.metrics,
            candidate_metrics=signatures.metrics,
            development_grade_ok=gbt.meets_min_grade,
        )
        status = assessment.status
        return_phase = None
        if status == PhaseGateStatus.PLATEAU_FAIL:
            if self._forcing_warning(evidence):
                status = PhaseGateStatus.FORCING_LIMIT
            else:
                return_phase = infer_rework_phase(signatures.metrics, self.kernel.phase_gate.policy)
        return (
            assessment,
            status,
            scheme_id,
            scheme_id,
            experiment_id,
            hydro,
            signatures,
            gbt,
            None,
            return_phase,
        )

    def _candidate_gate(self, task_id: str, evidence, phase: CalibrationPhase):
        repo = self.kernel.repository
        plan = self.kernel.evaluator.plan_for(task_id)
        cal = plan.calibration
        state = repo.get_task_state(task_id)
        optimize = next(
            (row for row in reversed(evidence) if row.action == ActionCode.A07_OPTIMIZE.value),
            None,
        )
        if optimize is None:
            raise RuntimeError("phase Gate requires a fresh optimization experiment")
        optimize_gates = dict(optimize.gates_json or {})
        candidate_hint = str(optimize_gates.get("candidate_scheme_id") or "")
        action_run = str(
            getattr(optimize, "action_run_id", None)
            or optimize_gates.get("optimizer_action_run_id")
            or optimize.evidence_id
        )
        experiment_id = str(optimize_gates.get("experiment_id") or "")
        if not experiment_id:
            experiment_id = calibration_experiment_id(
                action_run,
                candidate_hint,
                cal.start,
                cal.end,
            )
        prior_ids = {
            str((row.gates_json or {}).get("experiment_id") or "")
            for row in evidence
            if row.action == ActionCode.A08_GATE.value
        }
        if experiment_id in prior_ids:
            raise RuntimeError(f"duplicate Gate for calibration experiment {experiment_id}")

        base_id = str(optimize_gates.get("base_scheme_id") or state.current_scheme_id)
        candidate_id = candidate_hint
        if not candidate_id:
            raise RuntimeError("optimization evidence missing candidate_scheme_id")
        base_hydro, base_signatures = self.kernel.evaluator.evaluate_scheme(base_id, cal)
        candidate_hydro, candidate_signatures = self.kernel.evaluator.evaluate_scheme(candidate_id, cal)
        gbt = run_gbt_accuracy(
            candidate_hydro,
            self.kernel.skills.gbt_accuracy_config(
                area_km2=float(self.kernel.source.basin.get("area_km2") or 0.0)
            ),
        )
        assessment = self.kernel.phase_gate.evaluate(
            phase=phase,
            base_scheme_id=base_id,
            candidate_scheme_id=candidate_id,
            experiment_id=experiment_id,
            base_metrics=base_signatures.metrics,
            candidate_metrics=candidate_signatures.metrics,
            development_grade_ok=gbt.meets_min_grade,
        )
        point = SearchProgressPoint(
            experiment_id=experiment_id,
            phase=phase,
            value=assessment.progress_value,
            higher_is_better=assessment.higher_is_better,
        )
        convergence = self.kernel.convergence.evaluate(self._history(evidence, phase), point)
        if convergence.duplicate:
            raise RuntimeError(f"duplicate convergence point {experiment_id}")
        status = assessment.status
        if convergence.plateau and status != PhaseGateStatus.PHASE_PASS:
            status = (
                PhaseGateStatus.FORCING_LIMIT
                if self._forcing_warning(evidence)
                else PhaseGateStatus.PLATEAU_FAIL
            )
        return (
            assessment,
            status,
            base_id,
            candidate_id,
            experiment_id,
            candidate_hydro,
            candidate_signatures,
            gbt,
            convergence,
            None,
            base_signatures,
        )

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        del decision
        repo = self.kernel.repository
        evidence = repo.list_evidence(task_id)
        phase = self.kernel.protocol.phase_from_evidence(evidence)

        base_signatures = None
        if phase == CalibrationPhase.DEVELOPMENT_VALIDATION:
            (
                assessment,
                status,
                base_id,
                candidate_id,
                experiment_id,
                _hydro,
                signatures,
                gbt,
                convergence,
                return_phase,
            ) = self._development_gate(task_id, evidence, phase)
        else:
            (
                assessment,
                status,
                base_id,
                candidate_id,
                experiment_id,
                _hydro,
                signatures,
                gbt,
                convergence,
                return_phase,
                base_signatures,
            ) = self._candidate_gate(task_id, evidence, phase)

        metrics = {
            **{f"candidate_{k}": float(v) for k, v in signatures.metrics.items()},
            **{str(k): float(v) for k, v in assessment.metrics.items()},
            "phase_progress_value": float(assessment.progress_value),
            **gbt.as_metrics_dict(),
        }
        if base_signatures is not None:
            metrics.update({f"base_{k}": float(v) for k, v in base_signatures.metrics.items()})
        if convergence is not None:
            metrics["convergence_unique_points"] = float(convergence.unique_points)
            if convergence.gain is not None:
                metrics["convergence_gain"] = float(convergence.gain)
            if convergence.slope is not None:
                metrics["convergence_slope"] = float(convergence.slope)
            if convergence.span is not None:
                metrics["convergence_span"] = float(convergence.span)

        advance = status in {PhaseGateStatus.PHASE_PASS, PhaseGateStatus.PLATEAU_PASS}
        terminal_limit = status in {
            PhaseGateStatus.DATA_LIMIT,
            PhaseGateStatus.FORCING_LIMIT,
            PhaseGateStatus.STRUCTURAL_LIMIT,
            PhaseGateStatus.HARD_BUDGET,
        } or (status == PhaseGateStatus.PLATEAU_FAIL and return_phase is None)
        adopt = assessment.adopt_candidate and phase != CalibrationPhase.DEVELOPMENT_VALIDATION
        reasons = list(assessment.reasons)
        if convergence is not None:
            reasons.append(convergence.reason)
        if return_phase is not None:
            reasons.append(f"development_rework={return_phase.value}")

        observations = (
            f"calibration_phase={phase.value}",
            f"gate_status={status.value}",
            f"experiment_id={experiment_id}",
            f"progress_metric={assessment.progress_metric}",
            f"progress_value={assessment.progress_value:.6f}",
            f"adopt_candidate={adopt}",
            f"advance_phase={advance}",
            f"return_phase={return_phase.value if return_phase else '-'}",
            f"scheme_grade={gbt.scheme_grade}",
            *tuple(dict.fromkeys(reasons)),
        )
        gates = {
            "status": status.value,
            "calibration_phase": phase.value,
            "experiment_id": experiment_id,
            "base_scheme_id": base_id,
            "candidate_scheme_id": candidate_id,
            "adopt_candidate": "true" if adopt else "false",
            "advance_phase": "true" if advance else "false",
            "return_phase": return_phase.value if return_phase else "",
            "stop_search": "true" if terminal_limit or advance else "false",
            "higher_is_better": "true" if assessment.higher_is_better else "false",
            "progress_metric": assessment.progress_metric,
            "reasons": ",".join(dict.fromkeys(reasons)),
            "scheme_grade": gbt.scheme_grade,
            "gbt_report_json": json.dumps(gbt.model_dump(), ensure_ascii=False, sort_keys=True),
        }
        return EvidencePacket(
            evidence_id=f"ev-gate-{len(evidence)+1}",
            task_id=task_id,
            action=ActionCode.A08_GATE,
            status=status.value,  # type: ignore[arg-type]
            observations=observations,
            metrics=metrics,
            gates=gates,
            new_information_hash=information_hash(
                action=ActionCode.A08_GATE,
                status=status.value,
                observations=observations,
                metrics=metrics,
            ),
        )


class ProtocolResolveHandler:
    def __init__(self, repository):
        self.repository = repository

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        del decision
        evidence = self.repository.list_evidence(task_id)
        gate = next(
            (row for row in reversed(evidence) if row.action == ActionCode.A08_GATE.value),
            None,
        )
        if gate is None:
            raise RuntimeError("resolve requires phase Gate evidence")
        gates = dict(gate.gates_json or {})
        status = str(gates.get("status") or gate.status)
        adopt = str(gates.get("adopt_candidate") or "false").lower() == "true"
        candidate_id = str(gates.get("candidate_scheme_id") or "")
        if adopt and candidate_id:
            self.repository.update_task_state(task_id, current_scheme_id=candidate_id)
        return_phase = str(gates.get("return_phase") or "")
        observations = (
            f"resolve_status={status}",
            f"calibration_phase={gates.get('calibration_phase')}",
            f"return_phase={return_phase or '-'}",
            f"adopt_candidate={adopt}",
            f"current_scheme_id={self.repository.get_task_state(task_id).current_scheme_id}",
        )
        return EvidencePacket(
            evidence_id=f"ev-resolve-{len(evidence)+1}",
            task_id=task_id,
            action=ActionCode.A09_RESOLVE,
            status=status,  # type: ignore[arg-type]
            observations=observations,
            metrics={},
            gates={
                "status": status,
                "calibration_phase": str(gates.get("calibration_phase") or ""),
                "experiment_id": str(gates.get("experiment_id") or ""),
                "adopt_candidate": "true" if adopt else "false",
                "advance_phase": str(gates.get("advance_phase") or "false"),
                "return_phase": return_phase,
            },
            new_information_hash=information_hash(
                action=ActionCode.A09_RESOLVE,
                status=status,
                observations=observations,
                metrics={},
            ),
        )
