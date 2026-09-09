from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, WorldStateView
from hydro_agent.agent.world_state import WorldStateBuilder

__all__ = [
    "ActionCode",
    "AgentDecision",
    "AgentRuntime",
    "EvidencePacket",
    "WorldStateBuilder",
    "WorldStateView",
]


def __getattr__(name: str):
    if name == "AgentRuntime":
        from hydro_agent.agent.runtime import AgentRuntime

        return AgentRuntime
    raise AttributeError(name)
