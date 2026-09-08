from __future__ import annotations

from hydro_agent.agent.contracts import (
    MAX_AGENT_ROUNDS,
    MAX_OPTIMIZATION_CYCLES,
    BudgetSummary,
    EvidenceSummary,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.permissions import PermissionGate
from hydro_agent.execution.hashing import sha256_bytes


class WorldStateBuilder:
    def __init__(
        self, repository, *, model_id: str = "xaj", capabilities: frozenset[str] | None = None
    ):
        self.repository = repository
        self.model_id = model_id
        self.capabilities = capabilities or frozenset({"forecast", "calibrate", "validate"})

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
            )
            for row in evidence_rows[-5:]
        )
        forecasts = self.repository.list_forecasts(task_id)
        view = WorldStateView(
            task=TaskSummary(
                task_id=task.task_id,
                basin_id=task.basin_id,
                phase=task.phase,
                forcing_mode=task.forcing_mode,
                terminal_status=task.terminal_status,
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
                agent_rounds_remaining=max(0, MAX_AGENT_ROUNDS - state.agent_rounds_used),
                optimization_cycles_remaining=max(
                    0, MAX_OPTIMIZATION_CYCLES - state.optimization_cycles_used
                ),
                max_agent_rounds=MAX_AGENT_ROUNDS,
                max_optimization_cycles=MAX_OPTIMIZATION_CYCLES,
            ),
            evidence_summary=evidence_summary,
            latest_forecast_id=forecasts[-1].forecast_id if forecasts else None,
            last_information_hash=state.last_information_hash,
            last_decision_fingerprint=state.last_decision_fingerprint,
            needs_follow_up=bool(state.needs_follow_up),
        )
        safe = PermissionGate().safe_actions(view)
        return view.model_copy(
            update={
                "permissions": PermissionSummary(safe_actions=safe, paused=view.permissions.paused)
            }
        )


def world_state_hash(view: WorldStateView) -> str:
    return sha256_bytes(view.model_dump_json().encode("utf-8"))
