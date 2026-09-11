from __future__ import annotations

from functools import cached_property
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DisplayStage(FrozenDef):
    id: str
    label: str


class WorkflowAction(FrozenDef):
    id: str
    kind: Literal["runtime", "modeling"]
    label_zh: str
    title_running_zh: str
    title_done_zh: str
    explain_zh: str
    phases: tuple[Literal["B", "F", "E"], ...] = ()
    handler: str | None = None
    enabled: bool = True
    role: Literal["exploratory", "closeout", "both", "modeling"]
    display_stage: str
    display_node: str
    display_node_by_status: dict[str, str] = Field(default_factory=dict)
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()

    @model_validator(mode="after")
    def runtime_needs_handler(self) -> Self:
        if self.kind == "runtime" and self.enabled and not self.handler:
            raise ValueError(f"{self.id} is an enabled runtime action without a handler")
        if self.kind == "modeling" and self.handler:
            raise ValueError(f"{self.id} is modeling and must not declare an agent handler")
        return self


class WorkflowTransition(FrozenDef):
    from_ref: str = Field(alias="from")
    to: str
    condition: str
    label_zh: str | None = None
    variant: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class DiagramLane(FrozenDef):
    id: str
    label: str
    variant: str | None = None


class DiagramPhase(FrozenDef):
    id: str
    label: str
    fromCol: int
    toCol: int
    variant: str | None = None


class DiagramGroup(FrozenDef):
    id: str
    label: str
    lane: str
    fromCol: int
    toCol: int
    variant: str | None = None


class DiagramNode(FrozenDef):
    id: str
    lane: str
    col: int
    type: str
    label: str
    sublabel: str | None = None
    width: int | None = None
    yOffset: int | None = None


class DiagramView(FrozenDef):
    id: str
    label: str
    focus: tuple[str, ...]
    note: str | None = None


class DiagramEdge(FrozenDef):
    from_ref: str = Field(alias="from")
    to: str
    label: str | None = None
    variant: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class DiagramCard(FrozenDef):
    dot: str
    title: str
    items: tuple[str, ...]


class DiagramSpec(FrozenDef):
    visual_preset: str
    quality_profile: str
    html_name: str
    lanes: tuple[DiagramLane, ...]
    phases: tuple[DiagramPhase, ...]
    groups: tuple[DiagramGroup, ...]
    mainPath: tuple[str, ...]
    nodes: tuple[DiagramNode, ...]
    views: tuple[DiagramView, ...]
    extra_edges: tuple[DiagramEdge, ...] = ()
    cards: tuple[DiagramCard, ...] = ()


class WorkflowDefinition(FrozenDef):
    workflow_id: str
    version: str
    title_zh: str
    phases: tuple[Literal["B", "F", "E"], ...]
    display_stages: tuple[DisplayStage, ...]
    actions: tuple[WorkflowAction, ...]
    transitions: tuple[WorkflowTransition, ...]
    conditions: dict[str, str]
    diagram: DiagramSpec

    @cached_property
    def actions_by_id(self) -> dict[str, WorkflowAction]:
        return {action.id: action for action in self.actions}

    @cached_property
    def nodes_by_id(self) -> dict[str, DiagramNode]:
        return {node.id: node for node in self.diagram.nodes}

    def action(self, action_id: str) -> WorkflowAction | None:
        return self.actions_by_id.get(action_id)

    def display_node_for(self, action_id: str, status: str | None = None) -> str | None:
        action = self.actions_by_id.get(action_id)
        if action is None:
            return action_id if action_id in self.nodes_by_id else None
        if status:
            mapped = action.display_node_by_status.get(status)
            if mapped:
                return mapped
        return action.display_node

    def enabled_runtime(self) -> tuple[WorkflowAction, ...]:
        return tuple(a for a in self.actions if a.kind == "runtime" and a.enabled)

    @model_validator(mode="after")
    def cross_check(self) -> Self:
        ids = [action.id for action in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate action id")
        stage_ids = {stage.id for stage in self.display_stages}
        node_ids = {node.id for node in self.diagram.nodes}
        lane_ids = {lane.id for lane in self.diagram.lanes}
        for action in self.actions:
            if action.display_stage not in stage_ids:
                raise ValueError(f"{action.id} display_stage {action.display_stage} is unknown")
            if action.display_node not in node_ids:
                raise ValueError(f"{action.id} display_node {action.display_node} is missing")
            for status_node in action.display_node_by_status.values():
                if status_node not in node_ids:
                    raise ValueError(f"{action.id} status node {status_node} is missing")
        for node in self.diagram.nodes:
            if node.lane not in lane_ids:
                raise ValueError(f"node {node.id} lane {node.lane} is unknown")
        for ref in self.diagram.mainPath:
            if ref not in node_ids:
                raise ValueError(f"mainPath node {ref} is missing")
        known_refs = node_ids | set(ids)
        for transition in self.transitions:
            if transition.from_ref not in known_refs:
                raise ValueError(f"transition from {transition.from_ref} is unknown")
            if transition.to not in known_refs:
                raise ValueError(f"transition to {transition.to} is unknown")
            if transition.condition not in self.conditions:
                raise ValueError(f"condition {transition.condition} is not declared")
        for extra in self.diagram.extra_edges:
            if extra.from_ref not in node_ids or extra.to not in node_ids:
                raise ValueError(f"extra edge {extra.from_ref}->{extra.to} is missing a node")
        return self
