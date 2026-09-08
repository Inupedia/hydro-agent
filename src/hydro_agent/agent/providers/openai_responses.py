from __future__ import annotations

import argparse
import os
import sys

from hydro_agent.agent.contracts import AgentDecision, WorldStateView

SYSTEM_INSTRUCTIONS = """You are the Hydro-Agent decision module.
Choose exactly one ActionCode from the provided safe_actions.
Never invent continuous parameter vectors or call model processes.
strategy_id must be null unless the chosen action requires a listed strategy.
Return only a concise rationale_summary; do not include hidden chain-of-thought.
"""


class OpenAIResponsesDecisionProvider:
    def __init__(self, *, model: str, client):
        if not model:
            raise ValueError("model is required")
        self.model = model
        self.client = client

    def decide(self, view: WorldStateView) -> AgentDecision:
        response = self.client.responses.parse(
            model=self.model,
            input=[
                {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                {"role": "user", "content": view.model_dump_json()},
            ],
            text_format=AgentDecision,
        )
        decision = response.output_parsed
        if decision is None:
            raise RuntimeError("OpenAI response missing structured AgentDecision")
        return decision


def _smoke() -> int:
    model = os.environ.get("HYDRO_AGENT_LLM_MODEL")
    if not model:
        print("HYDRO_AGENT_LLM_MODEL is required for live smoke", file=sys.stderr)
        return 2
    try:
        from openai import OpenAI
    except ImportError:
        print("install optional dependency: uv sync --extra agent-openai", file=sys.stderr)
        return 2
    from hydro_agent.agent.contracts import (
        ActionCode,
        BudgetSummary,
        ModelSummary,
        PermissionSummary,
        SchemeSummary,
        TaskSummary,
    )

    view = WorldStateView(
        task=TaskSummary(task_id="smoke", basin_id="demo", phase="B", forcing_mode="R"),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="scheme-base", status="base", content_hash="h"),
        permissions=PermissionSummary(safe_actions=(ActionCode.A05_FORECAST,), paused=False),
        budget=BudgetSummary(
            agent_rounds_remaining=20,
            optimization_cycles_remaining=4,
            max_agent_rounds=20,
            max_optimization_cycles=4,
        ),
    )
    provider = OpenAIResponsesDecisionProvider(model=model, client=OpenAI())
    decision = provider.decide(view)
    print(decision.model_dump_json())
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke:
        raise SystemExit(_smoke())
    raise SystemExit("pass --smoke for live structured decision smoke test")
