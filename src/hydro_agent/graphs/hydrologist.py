from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class HydrologistTuneState(TypedDict, total=False):
    session_id: str
    step: str  # baseline | update_params | compare | submit
    params: dict[str, float]
    note: str
    task_id: str | None
    session: dict[str, Any]
    error: str | None


def build_hydrologist_tune_graph(service):
    """LangGraph for notebook §6: baseline → edit params → compare → submit candidate."""

    def baseline(state: HydrologistTuneState) -> dict[str, Any]:
        session = service.run_baseline(state["session_id"])
        return {"session": session, "error": session.get("error")}

    def update_params(state: HydrologistTuneState) -> dict[str, Any]:
        session = service.update_params(
            state["session_id"],
            state.get("params") or {},
            note=state.get("note") or "",
        )
        return {"session": session, "error": session.get("error")}

    def compare(state: HydrologistTuneState) -> dict[str, Any]:
        session = service.compare(state["session_id"])
        return {"session": session, "error": session.get("error")}

    def submit(state: HydrologistTuneState) -> dict[str, Any]:
        session = service.submit_candidate(
            state["session_id"], task_id=state.get("task_id")
        )
        return {"session": session, "error": session.get("error")}

    def route(state: HydrologistTuneState) -> str:
        step = state.get("step") or "baseline"
        return {
            "baseline": "baseline",
            "update_params": "update_params",
            "compare": "compare",
            "submit": "submit",
        }.get(step, END)

    graph = StateGraph(HydrologistTuneState)
    graph.add_node("baseline", baseline)
    graph.add_node("update_params", update_params)
    graph.add_node("compare", compare)
    graph.add_node("submit", submit)
    graph.add_conditional_edges(
        START,
        route,
        {
            "baseline": "baseline",
            "update_params": "update_params",
            "compare": "compare",
            "submit": "submit",
            END: END,
        },
    )
    graph.add_edge("baseline", END)
    graph.add_edge("update_params", END)
    graph.add_edge("compare", END)
    graph.add_edge("submit", END)
    return graph.compile()
