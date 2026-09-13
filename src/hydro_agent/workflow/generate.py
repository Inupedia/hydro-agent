from __future__ import annotations

import json
from pathlib import Path

from hydro_agent.workflow.conditions import known_condition_names
from hydro_agent.workflow.definition import current_binding, definition_hash, load_definition
from hydro_agent.workflow.handlers import assert_condition_implementations, assert_handlers_declared
from hydro_agent.workflow.models import WorkflowDefinition


def frontend_catalog(definition: WorkflowDefinition, *, file_hash: str) -> dict[str, object]:
    actions: dict[str, object] = {}
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
        "display_stages": [stage.model_dump() for stage in definition.display_stages],
        "step_order": [action.id for action in definition.enabled_runtime()],
        "actions": actions,
    }


def render_workflow_ts(catalog: dict[str, object]) -> str:
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
        "}\n"
    )


def render_workflow_meta_js(catalog: dict[str, object]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, indent=2)
    return (
        "/* Generated from workflow/hydro-agent.v*.json. Do not edit. */\n"
        f"window.HYDRO_WORKFLOW_META = {payload};\n"
    )


def derived_paths(repo_root: Path) -> dict[str, Path]:
    return {
        "frontend_ts": repo_root / "web" / "src" / "generated" / "workflow.ts",
        "frontend_js": repo_root / "web" / "public" / "workflow-meta.js",
    }


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
    catalog = frontend_catalog(definition, file_hash=file_hash)
    paths = derived_paths(repo_root)
    outputs = {
        paths["frontend_ts"]: render_workflow_ts(catalog),
        paths["frontend_js"]: render_workflow_meta_js(catalog),
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


def definition_api_payload(version: str | None = None) -> dict[str, object]:
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
