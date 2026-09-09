from __future__ import annotations

from typing import Protocol

from hydro_agent.agent.contracts import EvidencePacket
from hydro_agent.agent.permissions import PermissionGate
from hydro_agent.agent.tools import ToolRouter
from hydro_agent.agent.world_state import WorldStateBuilder
from hydro_agent.graphs.forecast import build_forecast_graph, run_forecast_until_terminal


class DecisionProvider(Protocol):
    def decide(self, view): ...


class AgentRuntime:
    """Forecast research loop backed by LangGraph (observe → decide → act)."""

    orchestrator = "langgraph"

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
        self._graph = build_forecast_graph(
            repository=repository,
            provider=provider,
            tools=tools,
            world_state=self.world_state,
            permissions=self.permissions,
            provider_name=provider_name,
            provider_model=provider_model,
        )

    def run_round(self, task_id: str) -> EvidencePacket:
        result = self._graph.invoke({"task_id": task_id})
        packet = result.get("last_packet")
        if packet is None:
            raise RuntimeError(
                f"forecast graph stopped without an action ({result.get('stop_reason') or 'unknown'})"
            )
        return packet

    def run_until_terminal(self, task_id: str) -> list[EvidencePacket]:
        return run_forecast_until_terminal(self._graph, task_id)
