from __future__ import annotations

import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from hydro_agent.agent.contracts import ActionCode, EvidencePacket
from hydro_agent.agent.experiment_guardrail import apply_experiment_plan_guardrail
from hydro_agent.agent.permissions import PermissionGate, decision_fingerprint
from hydro_agent.agent.tools import ToolExecutionContext, information_hash
from hydro_agent.agent.world_state import world_state_hash


class ForecastGraphState(TypedDict, total=False):
    task_id: str
    last_packet: EvidencePacket | None
    stop: bool
    stop_reason: str


def _attach_experiment_plan(packet: EvidencePacket, decision) -> EvidencePacket:
    if decision.action != ActionCode.A05_OPTIMIZE or not decision.experiment_plan_id:
        return packet
    observations = packet.observations + (
        f"experiment_plan_id={decision.experiment_plan_id}",
        f"experiment_signature={decision.experiment_signature or '-'}",
        "experiment_reason_codes=" + ",".join(decision.experiment_reason_codes),
        "experiment_evidence_refs=" + ",".join(decision.experiment_evidence_refs),
    )
    gates = {
        **packet.gates,
        "experiment_plan_id": decision.experiment_plan_id,
        "experiment_signature": decision.experiment_signature or "",
        "experiment_reason_codes": ",".join(decision.experiment_reason_codes),
        "experiment_evidence_refs": ",".join(decision.experiment_evidence_refs),
    }
    return packet.model_copy(
        update={
            "observations": observations,
            "gates": gates,
            "new_information_hash": information_hash(
                action=packet.action,
                status=packet.status,
                observations=observations,
                metrics=packet.metrics,
            ),
        }
    )


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
    from hydro_agent.workflow.handlers import assert_handlers_declared

    assert_handlers_declared()
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
        from hydro_agent.agent.providers.siliconflow import (
            _fallback_payload,
            normalize_decision_payload,
        )

        task_id = state["task_id"]
        view = world_state.build(task_id)
        decision = apply_experiment_plan_guardrail(view, provider.decide(view))
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
                available_param_groups=tuple(view.hydro.available_param_groups),
                available_strategies=tuple(view.hydro.available_strategies),
                model_id=str(view.model.model_id or "xaj"),
            )
            # Prefer forward progress over repeating the blocked decision.
            for preferred in (
                ActionCode.A06_GATE.value,
                ActionCode.A07_RESOLVE.value,
                ActionCode.A08_FREEZE.value,
                ActionCode.A05_OPTIMIZE.value,
                ActionCode.A04_DIAGNOSE.value,
                ActionCode.A03_FORECAST.value,
            ):
                if preferred in safe and preferred != decision.action.value:
                    fallback["action"] = preferred
                    if preferred != ActionCode.A05_OPTIMIZE.value:
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

            decision = apply_experiment_plan_guardrail(view, AD.model_validate(fallback))
            gate.authorize(view, decision)
        task_state = repository.get_task_state(task_id)
        round_number = task_state.agent_rounds_used + 1
        decision_id = f"dec-{uuid.uuid4().hex[:12]}"
        repository.record_agent_decision(
            decision_id=decision_id,
            task_id=task_id,
            round_number=round_number,
            provider=provider_name,
            model=provider_model,
            world_state_hash=world_state_hash(view),
            action=decision.action.value,
            hypothesis=decision.hypothesis.value,
            strategy_id=decision.strategy_id,
            rationale_summary=decision.rationale_summary,
            input_tokens=None,
            output_tokens=None,
            activated_skills_json=list(decision.activated_skills_audit),
            experience_audit_json=(
                {
                    "skill_version": decision.experience_skill_version,
                    "skill_hash": decision.experience_skill_hash,
                    "experience_refs": list(decision.experience_refs),
                    "mode": decision.experience_mode,
                    "influence": list(decision.experience_influence),
                }
                if decision.experience_skill_version is not None
                else None
            ),
        )
        packet = _attach_experiment_plan(
            tools.execute(
                task_id,
                decision,
                ToolExecutionContext(decision_id=decision_id, round_number=round_number),
            ),
            decision,
        )
        repository.add_evidence(packet)
        opt_used = task_state.optimization_cycles_used + (
            1 if decision.action == ActionCode.A05_OPTIMIZE else 0
        )
        needs_follow_up = True
        paused = None
        if decision.action == ActionCode.A10_EVALUATE_REPORT:
            needs_follow_up = False
        elif packet.status == "blocked":
            if "hydrologist_manual_required" in packet.observations:
                # Pause for notebook-style HITL; user submits candidate then resumes.
                paused = True
                needs_follow_up = True
            elif "campaign_stop_required_before_research_freeze" in packet.observations:
                # Premature freeze is not a terminal human handoff — keep the loop
                # so the next decide can re-diagnose or wait for a real Campaign stop.
                needs_follow_up = True
            else:
                needs_follow_up = False
        optimize_attempt = sum(
            1 for item in view.evidence_summary if item.action == ActionCode.A05_OPTIMIZE
        )
        update_kwargs = dict(
            agent_rounds_used=round_number,
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
