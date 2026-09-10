from __future__ import annotations

from hydro_agent.agent.contracts import (
    MAX_AGENT_ROUNDS,
    MAX_OPTIMIZATION_CYCLES,
    BudgetSummary,
    EvidenceSummary,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.permissions import PermissionGate
from hydro_agent.calibration.protocol import CalibrationProtocol
from hydro_agent.execution.hashing import sha256_bytes
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills import SkillRegistry
from hydro_agent.workbench.validation_gate import latest_candidate_scheme_id


class WorldStateBuilder:
    def __init__(
        self,
        repository,
        *,
        model_id: str = "xaj",
        capabilities: frozenset[str] | None = None,
        skills: SkillRegistry | None = None,
        strategies: CalibrationStrategyRegistry | None = None,
    ):
        self.repository = repository
        self.model_id = model_id
        self.capabilities = capabilities or frozenset({"forecast", "calibrate", "validate"})
        self.skills = skills or SkillRegistry()
        self.strategies = strategies or CalibrationStrategyRegistry()

    def build(self, task_id: str) -> WorldStateView:
        task = self.repository.get_task(task_id)
        state = self.repository.ensure_task_state(task_id)
        scheme = self.repository.get_scheme(state.current_scheme_id)
        evidence_rows = self.repository.list_evidence(task_id)
        evidence_summary = tuple(
            EvidenceSummary(
                evidence_id=row.evidence_id,
                action=row.action,
                status=row.status,
                new_information_hash=row.new_information_hash,
                observations=tuple(row.observations_json or ()),
                metrics={str(k): float(v) for k, v in dict(row.metrics_json or {}).items()},
                gates={str(k): str(v) for k, v in dict(row.gates_json or {}).items()},
            )
            for row in evidence_rows[-8:]
        )
        forecasts = [
            row
            for row in self.repository.list_forecasts(task_id)
            if row.scheme_id == scheme.scheme_id
        ]
        forecasts.sort(key=lambda row: (row.issue_time, row.forecast_id))
        latest_forecast = forecasts[-1] if forecasts else None
        current_params = dict((scheme.config_json or {}).get("parameters") or {})
        candidate = None
        candidate_id = latest_candidate_scheme_id(self.repository, task_id)
        if candidate_id and candidate_id != scheme.scheme_id:
            try:
                candidate = self.repository.get_scheme(candidate_id)
            except KeyError:
                candidate = None
        candidate_params = None
        parameter_delta: dict[str, float] = {}
        if candidate is not None:
            candidate_params = dict((candidate.config_json or {}).get("parameters") or {})
            for key, value in candidate_params.items():
                if key in current_params:
                    parameter_delta[key] = float(value) - float(current_params[key])
        diagnosis = {}
        for row in reversed(evidence_rows):
            if row.action == "A06_DIAGNOSE" and row.gates_json:
                diagnosis = dict(row.gates_json)
                diagnosis["metrics"] = {
                    str(k): float(v) for k, v in dict(row.metrics_json or {}).items()
                }
                break
        history = tuple(
            f"{row.action}:{row.status}:{';'.join((row.observations_json or [])[:2])}"
            for row in evidence_rows[-6:]
        )
        protocol = CalibrationProtocol()
        calibration_phase = protocol.phase_from_evidence(evidence_rows)
        hydro = HydroContext(
            current_parameters={k: float(v) for k, v in current_params.items()},
            candidate_parameters=candidate_params,
            parameter_delta=parameter_delta,
            latest_forecast_leads=(
                {int(k): float(v) for k, v in latest_forecast.lead_values_json.items()}
                if latest_forecast
                else {}
            ),
            available_skills=self.skills.summaries_zh(),
            available_strategies=tuple(
                sid
                for sid in self.strategies.list_ids()
                if sid != "xaj-hydrologist-manual-v1"
            )
            or self.strategies.list_ids(),
            available_param_groups=("evap", "runoff", "routing"),
            available_objectives=("nse", "peak", "composite"),
            diagnosis=diagnosis,
            calibration_phase=calibration_phase.value,
            phase_history=protocol.phase_history(evidence_rows),
            experiment_history=history,
            skill_cards=tuple(self.skills.cards_for_prompt()),
        )
        workbench = dict((scheme.config_json or {}).get("workbench") or {})
        allow_optimization = bool(workbench.get("allow_optimization", True))
        max_rounds = int(workbench.get("max_agent_decision_rounds") or MAX_AGENT_ROUNDS)
        max_opt = int(
            workbench["max_optimization_cycles"]
            if "max_optimization_cycles" in workbench
            else MAX_OPTIMIZATION_CYCLES
        )
        max_rounds = max(1, min(max_rounds, 100))
        max_opt = max(0, min(max_opt, 20))
        view = WorldStateView(
            task=TaskSummary(
                task_id=task.task_id,
                basin_id=task.basin_id,
                phase=task.phase,
                forcing_mode=task.forcing_mode,
                terminal_status=task.terminal_status,
                allow_optimization=allow_optimization,
            ),
            model=ModelSummary(
                model_id=self.model_id, capabilities=tuple(sorted(self.capabilities))
            ),
            scheme=SchemeSummary(
                scheme_id=scheme.scheme_id,
                status=scheme.status,
                content_hash=scheme.content_hash,
            ),
            permissions=PermissionSummary(safe_actions=(), paused=bool(state.paused)),
            budget=BudgetSummary(
                agent_rounds_remaining=max(0, max_rounds - state.agent_rounds_used),
                optimization_cycles_remaining=max(0, max_opt - state.optimization_cycles_used),
                max_agent_rounds=max_rounds,
                max_optimization_cycles=max_opt,
            ),
            evidence_summary=evidence_summary,
            latest_forecast_id=latest_forecast.forecast_id if latest_forecast else None,
            last_information_hash=state.last_information_hash,
            last_decision_fingerprint=state.last_decision_fingerprint,
            needs_follow_up=bool(state.needs_follow_up),
            hydro=hydro,
        )
        safe = PermissionGate().safe_actions(view)
        return view.model_copy(
            update={
                "permissions": PermissionSummary(safe_actions=safe, paused=view.permissions.paused)
            }
        )


def world_state_hash(view: WorldStateView) -> str:
    return sha256_bytes(view.model_dump_json().encode("utf-8"))
