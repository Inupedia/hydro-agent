from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket, WorldStateView

__all__ = [
    "ActionCode",
    "AgentDecision",
    "AgentRuntime",
    "EvidencePacket",
    "WorldStateBuilder",
    "WorldStateView",
]


def __getattr__(name: str):
    # Keep package import side-effect free. world_state depends on workbench validation
    # helpers, while those helpers import agent.contracts; eager import creates a cycle.
    if name == "AgentRuntime":
        from hydro_agent.agent.runtime import AgentRuntime

        return AgentRuntime
    if name == "WorldStateBuilder":
        from hydro_agent.agent.world_state import WorldStateBuilder

        return WorldStateBuilder
    raise AttributeError(name)
