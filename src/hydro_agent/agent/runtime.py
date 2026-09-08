from __future__ import annotations

import uuid
from typing import Protocol

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, WorldStateView
from hydro_agent.agent.permissions import PermissionGate, decision_fingerprint
from hydro_agent.agent.tools import ToolRouter
from hydro_agent.agent.world_state import WorldStateBuilder, world_state_hash


class DecisionProvider(Protocol):
    def decide(self, view: WorldStateView) -> AgentDecision: ...


class AgentRuntime:
    def __init__(
        self,
        repository,
        *,
        provider: DecisionProvider,
        tools: ToolRouter,
        world_state: WorldStateBuilder | None = None,
        permissions: PermissionGate | None = None,
        provider_name: str = "scripted",
        provider_model: str | None = None,
    ):
        self.repository = repository
        self.provider = provider
        self.tools = tools
        self.world_state = world_state or WorldStateBuilder(repository)
        self.permissions = permissions or PermissionGate()
        self.provider_name = provider_name
        self.provider_model = provider_model

    def run_round(self, task_id: str) -> EvidencePacket:
        view = self.world_state.build(task_id)
        decision = self.provider.decide(view)
        self.permissions.authorize(view, decision)
        packet = self.tools.execute(task_id, decision)
        self.repository.add_evidence(packet)
        state = self.repository.get_task_state(task_id)
        rounds_used = state.agent_rounds_used + 1
        opt_used = state.optimization_cycles_used + (
            1 if decision.action == ActionCode.A07_OPTIMIZE else 0
        )
        needs_follow_up = True
        if decision.action == ActionCode.A09_RESOLVE:
            needs_follow_up = False
        elif decision.action == ActionCode.A12_EVALUATE_REPORT:
            needs_follow_up = False
        elif packet.status == "blocked":
            needs_follow_up = False
        self.repository.update_task_state(
            task_id,
            agent_rounds_used=rounds_used,
            optimization_cycles_used=opt_used,
            last_information_hash=packet.new_information_hash,
            last_decision_fingerprint=decision_fingerprint(decision, view.scheme.scheme_id),
            needs_follow_up=needs_follow_up,
        )
        self.repository.record_agent_decision(
            decision_id=f"dec-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            round_number=rounds_used,
            provider=self.provider_name,
            model=self.provider_model,
            world_state_hash=world_state_hash(view),
            action=decision.action.value,
            hypothesis=decision.hypothesis.value,
            strategy_id=decision.strategy_id,
            rationale_summary=decision.rationale_summary,
            input_tokens=None,
            output_tokens=None,
        )
        return packet

    def run_until_terminal(self, task_id: str) -> list[EvidencePacket]:
        packets: list[EvidencePacket] = []
        while True:
            view = self.world_state.build(task_id)
            if (
                not view.needs_follow_up
                or view.permissions.paused
                or view.task.terminal_status
                or view.budget.agent_rounds_remaining <= 0
            ):
                break
            packets.append(self.run_round(task_id))
        return packets
