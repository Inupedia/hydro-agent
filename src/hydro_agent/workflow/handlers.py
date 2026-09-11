from __future__ import annotations

from hydro_agent.agent.contracts import ActionCode
from hydro_agent.workflow.definition import load_definition
from hydro_agent.workflow.models import WorkflowDefinition

HANDLER_TO_ACTION = {
    "check_data": ActionCode.A01_CHECK_DATA,
    "repair_data": ActionCode.A02_REPAIR_DATA,
    "validate_scheme": ActionCode.A03_VALIDATE_SCHEME,
    "rebuild_state": ActionCode.A04_REBUILD_STATE,
    "forecast": ActionCode.A05_FORECAST,
    "diagnose": ActionCode.A06_DIAGNOSE,
    "optimize": ActionCode.A07_OPTIMIZE,
    "gate": ActionCode.A08_GATE,
    "resolve": ActionCode.A09_RESOLVE,
    "freeze": ActionCode.A10_FREEZE,
    "replay": ActionCode.A11_REPLAY,
    "evaluate": ActionCode.A12_EVALUATE_REPORT,
}


class WorkflowIntegrityError(ValueError):
    pass


def assert_handlers_declared(definition: WorkflowDefinition | None = None) -> None:
    definition = definition or load_definition()
    for action in definition.actions:
        if action.kind != "runtime" or not action.handler:
            continue
        expected = HANDLER_TO_ACTION.get(action.handler)
        if expected is None:
            raise WorkflowIntegrityError(f"unknown handler {action.handler} for {action.id}")
        if expected.value != action.id:
            raise WorkflowIntegrityError(
                f"handler {action.handler} is registered to {expected.value}, not {action.id}"
            )


def assert_tool_router(tools, definition: WorkflowDefinition | None = None) -> None:
    """Every enabled runtime action must have a ToolRouter handler."""
    definition = definition or load_definition()
    assert_handlers_declared(definition)
    registered = set(getattr(tools, "_handlers", {}) or {})
    missing = []
    for action in definition.enabled_runtime():
        code = ActionCode(action.id)
        if code not in registered:
            missing.append(action.id)
    if missing:
        raise WorkflowIntegrityError(f"tool router missing handlers: {missing}")


def assert_condition_implementations(definition: WorkflowDefinition | None = None) -> None:
    from hydro_agent.workflow.conditions import known_condition_names

    definition = definition or load_definition()
    known = known_condition_names()
    unknown = sorted(name for name in definition.conditions if name not in known)
    if unknown:
        raise WorkflowIntegrityError(f"conditions lack code implementations: {unknown}")
