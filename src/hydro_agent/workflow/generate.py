from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hydro_agent.workflow.conditions import known_condition_names
from hydro_agent.workflow.definition import (
    current_binding,
    definition_hash,
    load_definition,
    version_html_names,
)
from hydro_agent.workflow.handlers import assert_condition_implementations, assert_handlers_declared
from hydro_agent.workflow.models import WorkflowDefinition, WorkflowTransition

STATUS_EDGE_LABEL = {
    "ACCEPT": "采用候选",
    "KEEP": "提升不够",
    "ROLLBACK": "触发限制",
}
CONDITION_EDGE_ROLE = {
    "gate_retry_allowed": "return",
    "blocked": "error",
}
CONDITION_EDGE_VARIANT = {
    "needs_calibration": "emphasis",
    "calibration_good_enough": "dashed",
    "candidate_ready": "emphasis",
    "gate_retry_allowed": "dashed",
    "gate_accept_or_stop": "default",
    "blocked": "security",
    "new_build": "default",
    "reuse_plan": "default",
}


def resolve_node(definition: WorkflowDefinition, ref: str, status: str | None = None) -> str:
    mapped = definition.display_node_for(ref, status)
    if mapped:
        return mapped
    return ref


def _expand_transition(
    definition: WorkflowDefinition, transition: WorkflowTransition
) -> list[dict[str, Any]]:
    """Turn one domain transition into one or more Archify edges."""
    from_action = definition.action(transition.from_ref)
    to_action = definition.action(transition.to)
    variant = transition.variant or CONDITION_EDGE_VARIANT.get(transition.condition, "default")
    role = CONDITION_EDGE_ROLE.get(transition.condition)
    label = transition.label_zh

    if from_action and from_action.display_node_by_status:
        if transition.condition == "gate_accept_or_stop":
            dest = resolve_node(definition, transition.to)
            return [
                _edge("accept", dest, label, "emphasis"),
                _edge("keep", dest, "停止搜索", "default"),
                _edge("rollback", dest, "停止搜索", "default"),
            ]
        if transition.condition == "gate_retry_allowed":
            dest = resolve_node(definition, transition.to)
            return [
                _edge("keep", dest, label, "dashed", role=role),
                _edge("rollback", dest, label, "dashed", role=role),
            ]
        if transition.condition == "blocked":
            return [
                _edge("keep", "blocked", label, "security", role=role),
                _edge("rollback", "blocked", label, "security", role=role),
            ]
        return [
            _edge(
                resolve_node(definition, transition.from_ref, status),
                resolve_node(definition, transition.to),
                label,
                variant,
            )
            for status in from_action.display_node_by_status
            if status not in {"blocked", "failed"}
        ]

    if to_action and to_action.display_node_by_status and transition.condition == "always":
        return [
            _edge(
                resolve_node(definition, transition.from_ref),
                node,
                label if status == "KEEP" and label else STATUS_EDGE_LABEL.get(status, status),
                "security" if status != "ACCEPT" else "emphasis",
            )
            for status, node in to_action.display_node_by_status.items()
            if status not in {"blocked", "failed"}
        ]

    return [
        _edge(
            resolve_node(definition, transition.from_ref),
            resolve_node(definition, transition.to),
            label,
            variant,
            role=role,
        )
    ]


def _edge(
    src: str,
    dst: str,
    label: str | None,
    variant: str,
    *,
    route: str | None = None,
    role: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": f"e-{src}-{dst}",
        "from": src,
        "to": dst,
        "variant": variant,
    }
    if label:
        payload["label"] = label
    if route:
        payload["route"] = route
    if role:
        payload["role"] = role
    return payload


def archify_document(
    definition: WorkflowDefinition, *, source_path: str, file_hash: str
) -> dict[str, Any]:
    diagram = definition.diagram
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for transition in definition.transitions:
        for edge in _expand_transition(definition, transition):
            pair = (edge["from"], edge["to"])
            if pair in seen or edge["from"] == edge["to"]:
                continue
            seen.add(pair)
            edges.append(edge)
    for extra in diagram.extra_edges:
        pair = (extra.from_ref, extra.to)
        if pair in seen:
            continue
        seen.add(pair)
        edges.append(_edge(extra.from_ref, extra.to, extra.label, extra.variant or "dashed"))

    def dump_model(item: Any, *, drop: set[str] | None = None) -> dict[str, Any]:
        data = item.model_dump(by_alias=True, exclude_none=True)
        for key in drop or ():
            data.pop(key, None)
        return data

    lanes = [dump_model(lane) for lane in diagram.lanes]
    nodes = [dump_model(node) for node in diagram.nodes]
    views = [dump_model(view) for view in diagram.views]
    groups = [dump_model(group) for group in diagram.groups]
    phases = [dump_model(phase) for phase in diagram.phases]
    cards = [dump_model(card) for card in diagram.cards]

    return {
        "schema_version": 2,
        "diagram_type": "workflow",
        "meta": {
            "title": definition.title_zh,
            "subtitle": f"{source_path} · {definition.version} · {file_hash}",
            "animation": "none",
            "visual_preset": diagram.visual_preset,
            "quality_profile": diagram.quality_profile,
            "views": views,
            "output": f"web/public/diagrams/{diagram.html_name}",
        },
        "lanes": lanes,
        "phases": phases,
        "groups": groups,
        "mainPath": list(diagram.mainPath),
        "nodes": nodes,
        "edges": edges,
        "cards": cards,
    }


def frontend_catalog(definition: WorkflowDefinition, *, file_hash: str) -> dict[str, Any]:
    actions = {}
    for action in definition.actions:
        actions[action.id] = {
            "kind": action.kind,
            "enabled": action.enabled,
            "label_zh": action.label_zh,
            "title_running_zh": action.title_running_zh,
            "title_done_zh": action.title_done_zh,
            "explain_zh": action.explain_zh,
            "display_stage": action.display_stage,
            "display_node": action.display_node,
            "display_node_by_status": dict(action.display_node_by_status),
        }
    return {
        "workflow_id": definition.workflow_id,
        "version": definition.version,
        "hash": file_hash,
        "html_name": definition.diagram.html_name,
        "diagrams_by_version": version_html_names(),
        "display_stages": [stage.model_dump() for stage in definition.display_stages],
        "step_order": [action.id for action in definition.enabled_runtime()],
        "actions": actions,
    }


def render_workflow_ts(catalog: dict[str, Any]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, indent=2)
    return (
        "/** Generated from workflow/hydro-agent.v*.json. Do not edit. */\n"
        f"export const WORKFLOW = {payload} as const\n\n"
        "export type WorkflowCatalog = typeof WORKFLOW\n"
        "export type AudienceStageId = (typeof WORKFLOW.display_stages)[number]['id']\n\n"
        "export function displayNodeFor(action: string | null | undefined, status?: string | null): string | null {\n"
        "  if (!action) return null\n"
        "  const item = WORKFLOW.actions[action as keyof typeof WORKFLOW.actions]\n"
        "  if (!item) return null\n"
        "  if (status && item.display_node_by_status && status in item.display_node_by_status) {\n"
        "    return item.display_node_by_status[status as keyof typeof item.display_node_by_status]\n"
        "  }\n"
        "  return item.display_node\n"
        "}\n\n"
        "export function diagramHtmlFor(version?: string | null): string {\n"
        "  if (!version || version === WORKFLOW.version) return WORKFLOW.html_name\n"
        "  const mapped = WORKFLOW.diagrams_by_version[version as keyof typeof WORKFLOW.diagrams_by_version]\n"
        "  return mapped || WORKFLOW.html_name\n"
        "}\n"
    )


def render_workflow_meta_js(catalog: dict[str, Any]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, indent=2)
    return (
        "/* Generated from workflow/hydro-agent.v*.json. Do not edit. */\n"
        f"window.HYDRO_WORKFLOW_META = {payload};\n"
    )


def derived_paths(repo_root: Path, definition: WorkflowDefinition) -> dict[str, Path]:
    html_name = definition.diagram.html_name
    json_name = html_name.replace(".html", ".json")
    return {
        "archify": repo_root / "docs" / "diagrams" / json_name,
        "archify_legacy": repo_root / "docs" / "diagrams" / "hydro-agent.workflow.json",
        "archify_xaj": repo_root / "docs" / "diagrams" / "hydro-agent-xaj.workflow.json",
        "frontend_ts": repo_root / "web" / "src" / "generated" / "workflow.ts",
        "frontend_js": repo_root / "web" / "public" / "workflow-meta.js",
        "html": repo_root / "web" / "public" / "diagrams" / html_name,
        "html_xaj": repo_root / "web" / "public" / "diagrams" / "hydro-agent-xaj.workflow.html",
    }


def dumps_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def sync_derived(repo_root: Path, *, check: bool = False) -> list[Path]:
    from hydro_agent.workflow.definition import definition_path

    path = definition_path()
    raw = path.read_bytes()
    definition = load_definition()
    assert_handlers_declared(definition)
    assert_condition_implementations(definition)
    unknown = sorted(name for name in definition.conditions if name not in known_condition_names())
    if unknown:
        raise ValueError(f"undeclared condition implementations: {unknown}")
    file_hash = definition_hash(raw)
    source = str(path.relative_to(repo_root))
    catalog = frontend_catalog(definition, file_hash=file_hash)
    archify = archify_document(definition, source_path=source, file_hash=file_hash)
    outputs = {
        derived_paths(repo_root, definition)["archify"]: dumps_json(archify),
        derived_paths(repo_root, definition)["archify_legacy"]: dumps_json(archify),
        derived_paths(repo_root, definition)["archify_xaj"]: dumps_json(archify),
        derived_paths(repo_root, definition)["frontend_ts"]: render_workflow_ts(catalog),
        derived_paths(repo_root, definition)["frontend_js"]: render_workflow_meta_js(catalog),
    }
    drifted: list[Path] = []
    written: list[Path] = []
    for target, content in outputs.items():
        existing = target.read_text(encoding="utf-8") if target.is_file() else None
        if existing != content:
            drifted.append(target)
            if not check:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written.append(target)
    if check and drifted:
        names = ", ".join(str(path.relative_to(repo_root)) for path in drifted)
        raise SystemExit(f"workflow artifacts drifted: {names}")
    return written if not check else []


def definition_api_payload(version: str | None = None) -> dict[str, Any]:
    from hydro_agent.workflow.definition import definition_path

    path = definition_path(version)
    raw = path.read_bytes()
    definition = WorkflowDefinition.model_validate_json(raw)
    file_hash = definition_hash(raw)
    binding = current_binding(definition.version)
    return {
        **binding,
        "version": definition.version,
        "title_zh": definition.title_zh,
        "phases": list(definition.phases),
        "html_name": definition.diagram.html_name,
        "diagrams_by_version": version_html_names(),
        "display_stages": [stage.model_dump() for stage in definition.display_stages],
        "actions": frontend_catalog(definition, file_hash=file_hash)["actions"],
        "step_order": [action.id for action in definition.enabled_runtime()],
        "transitions": [
            {
                "from": item.from_ref,
                "to": item.to,
                "condition": item.condition,
                "label_zh": item.label_zh,
            }
            for item in definition.transitions
        ],
    }
