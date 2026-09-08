from __future__ import annotations

from hydro_agent.agent.contracts import AgentDecision, WorldStateView


class ScriptedDecisionProvider:
    """Deterministic provider that returns queued AgentDecision values in order."""

    def __init__(self, decisions: list[AgentDecision] | None = None):
        self._queue: list[AgentDecision] = list(decisions or [])
        self.seen_views: list[WorldStateView] = []

    def queue(self, decisions: list[AgentDecision]) -> None:
        self._queue.extend(decisions)

    def decide(self, view: WorldStateView) -> AgentDecision:
        self.seen_views.append(view)
        if not self._queue:
            raise RuntimeError("scripted provider queue is empty")
        return self._queue.pop(0)
