from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from hydro_agent.agent.contracts import ActionCode, EvidencePacket
from hydro_agent.agent.permissions import PermissionGate, decision_fingerprint
from hydro_agent.agent.world_state import world_state_hash


class ForecastGraphState(TypedDict, total=False):
    task_id: str
    last_packet: EvidencePacket | None
    stop: bool
    stop_reason: str


def build_forecast_graph(
    *,
    repository,
    provider,
    tools,
    world_state,
    permissions: PermissionGate | None = None,
    provider_name: str = "scripted",
    provider_model: str | None = None,
):
    """Compile a single-round LangGraph: observe → (act | end)."""
    gate = permissions or PermissionGate()

    def observe(state: ForecastGraphState) -> dict[str, Any]:
        from hydro_agent.agent.permissions import closeout_pending

        task_id = state["task_id"]
        view = world_state.build(task_id)
        if not view.needs_follow_up or view.permissions.paused or view.task.terminal_status:
            reason = "paused" if view.permissions.paused else "terminal"
            return {"stop": True, "stop_reason": reason, "last_packet": None}
        # Budget exhausted stops exploration — but never blocks freeze/replay/evaluate.
        if view.budget.agent_rounds_remaining <= 0 and not closeout_pending(view):
            return {"stop": True, "stop_reason": "budget_exhausted", "last_packet": None}
        if not view.permissions.safe_actions and not closeout_pending(view):
            return {"stop": True, "stop_reason": "no_safe_actions", "last_packet": None}
        return {"stop": False, "stop_reason": ""}

    def act(state: ForecastGraphState) -> dict[str, Any]:
        from hydro_agent.agent.permissions import PermissionDenied
        from hydro_agent.agent.providers.siliconflow import _fallback_payload, normalize_decision_payload

        task_id = state["task_id"]
        view = world_state.build(task_id)
        decision = provider.decide(view)
        try:
            gate.authorize(view, decision)
        except PermissionDenied:
            # Recover from fingerprint stalls by taking the deterministic next step.
            safe = {a.value for a in view.permissions.safe_actions}
            evidence_actions = tuple(item.action.value for item in view.evidence_summary)
            fallback = normalize_decision_payload(
                _fallback_payload(view, raw_text="no new evidence recovery"),
                safe_actions=safe,
                evidence_actions=evidence_actions,
            )
            # Prefer forward progress over repeating the blocked decision.
            for preferred in (
                ActionCode.A08_GATE.value,
                ActionCode.A09_RESOLVE.value,
                ActionCode.A10_FREEZE.value,
                ActionCode.A07_OPTIMIZE.value,
                ActionCode.A06_DIAGNOSE.value,
                ActionCode.A05_FORECAST.value,
            ):
                if preferred in safe and preferred != decision.action.value:
                    fallback["action"] = preferred
                    if preferred != ActionCode.A07_OPTIMIZE.value:
                        fallback["strategy_id"] = None
                        fallback["param_groups"] = None
                        fallback["objective"] = None
                    else:
                        fallback["strategy_id"] = fallback.get("strategy_id") or "xaj-bounded-v1"
                        fallback["param_groups"] = fallback.get("param_groups") or [
                            "evap",
                            "runoff",
                            "routing",
                        ]
                        fallback["objective"] = fallback.get("objective") or "nse"
                    fallback["rationale_summary"] = (
                        f"恢复推进：原决策 {decision.action.value} 无新证据，改为 {preferred}。"
                    )
                    break
            from hydro_agent.agent.contracts import AgentDecision as AD

            decision = AD.model_validate(fallback)
            gate.authorize(view, decision)
        packet = tools.execute(task_id, decision)
        repository.add_evidence(packet)
        task_state = repository.get_task_state(task_id)
        rounds_used = task_state.agent_rounds_used + 1
        opt_used = task_state.optimization_cycles_used + (
            1 if decision.action == ActionCode.A07_OPTIMIZE else 0
        )
        needs_follow_up = True
        paused = None
        if decision.action == ActionCode.A12_EVALUATE_REPORT:
            needs_follow_up = False
        elif packet.status == "blocked":
            if "hydrologist_manual_required" in packet.observations:
                # Pause for notebook-style HITL; user submits candidate then resumes.
                paused = True
                needs_follow_up = True
            else:
                needs_follow_up = False
        optimize_attempt = sum(
            1 for item in view.evidence_summary if item.action == ActionCode.A07_OPTIMIZE
        )
        update_kwargs = dict(
            agent_rounds_used=rounds_used,
            optimization_cycles_used=opt_used,
            last_information_hash=packet.new_information_hash,
            last_decision_fingerprint=decision_fingerprint(
                decision, view.scheme.scheme_id, optimize_attempt=optimize_attempt
            ),
            needs_follow_up=needs_follow_up,
        )
        if paused is not None:
            update_kwargs["paused"] = paused
        repository.update_task_state(task_id, **update_kwargs)
        repository.record_agent_decision(
            decision_id=f"dec-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            round_number=rounds_used,
            provider=provider_name,
            model=provider_model,
            world_state_hash=world_state_hash(view),
            action=decision.action.value,
            hypothesis=decision.hypothesis.value,
            strategy_id=decision.strategy_id,
            rationale_summary=decision.rationale_summary,
            input_tokens=None,
            output_tokens=None,
        )
        return {"last_packet": packet, "stop": False, "stop_reason": ""}

    def route_after_observe(state: ForecastGraphState) -> str:
        return END if state.get("stop") else "act"

    graph = StateGraph(ForecastGraphState)
    graph.add_node("observe", observe)
    graph.add_node("act", act)
    graph.add_edge(START, "observe")
    graph.add_conditional_edges("observe", route_after_observe, {END: END, "act": "act"})
    graph.add_edge("act", END)
    return graph.compile()


def run_forecast_until_terminal(compiled, task_id: str) -> list[EvidencePacket]:
    """Invoke the single-round graph until observe reports a stop condition."""
    packets: list[EvidencePacket] = []
    while True:
        result = compiled.invoke({"task_id": task_id})
        if result.get("stop") and result.get("last_packet") is None:
            break
        packet = result.get("last_packet")
        if packet is None:
            break
        packets.append(packet)
    return packets
