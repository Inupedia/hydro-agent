from hydro_agent.agent.contracts import ActionCode
from hydro_agent.agent.permissions import (
    CLOSEOUT_ACTIONS,
    EXPLORATORY_ACTIONS,
    PHASE_ACTIONS,
)
from hydro_agent.workflow.definition import current_binding, load_definition
from hydro_agent.workflow.generate import frontend_catalog
from hydro_agent.workflow.handlers import (
    assert_condition_implementations,
    assert_handlers_declared,
)


def test_v2_definition_matches_runtime_permissions():
    definition = load_definition()
    assert definition.workflow_id == "hydro-agent-calibration"
    assert definition.version == "2.0.0"
    assert definition.action("A04_DIAGNOSE").display_node == "diagnose"
    assert definition.display_node_for("A07_RESOLVE", "ACCEPT") == "accept"
    assert definition.display_node_for("A07_RESOLVE", "KEEP") == "keep"
    assert definition.display_node_for("A07_RESOLVE", "ROLLBACK") == "rollback"
    assert tuple(action.id for action in definition.enabled_runtime()) == tuple(
        f"A{number:02d}_{action.id.split('_', 1)[1]}"
        for number, action in enumerate(definition.enabled_runtime(), start=1)
    )
    assert PHASE_ACTIONS["B"] == {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A02_VALIDATE_SCHEME,
        ActionCode.A03_FORECAST,
        ActionCode.A04_DIAGNOSE,
        ActionCode.A05_OPTIMIZE,
        ActionCode.A06_GATE,
        ActionCode.A07_RESOLVE,
        ActionCode.A08_FREEZE,
    }
    assert PHASE_ACTIONS["F"] == {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A02_VALIDATE_SCHEME,
        ActionCode.A03_FORECAST,
        ActionCode.A07_RESOLVE,
        ActionCode.A09_REPLAY,
    }
    assert PHASE_ACTIONS["E"] == {ActionCode.A10_EVALUATE_REPORT, ActionCode.A01_CHECK_DATA}
    assert EXPLORATORY_ACTIONS == {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A02_VALIDATE_SCHEME,
        ActionCode.A03_FORECAST,
        ActionCode.A04_DIAGNOSE,
        ActionCode.A05_OPTIMIZE,
    }
    assert CLOSEOUT_ACTIONS == {
        ActionCode.A06_GATE,
        ActionCode.A07_RESOLVE,
        ActionCode.A08_FREEZE,
        ActionCode.A09_REPLAY,
        ActionCode.A10_EVALUATE_REPORT,
    }
    assert_handlers_declared(definition)
    assert_condition_implementations(definition)


def test_binding_hash_is_stable_and_prefixed():
    binding = current_binding()
    assert binding["workflow_id"] == "hydro-agent-calibration"
    assert binding["workflow_version"] == "2.0.0"
    assert binding["workflow_hash"].startswith("sha256:")
    assert len(binding["workflow_hash"]) == 7 + 64


def test_frontend_catalog_preserves_branching_workflow_metadata():
    definition = load_definition()
    binding = current_binding()
    catalog = frontend_catalog(definition, file_hash=binding["workflow_hash"])

    actions = catalog["actions"]
    assert actions["A04_DIAGNOSE"]["display_node"] == "diagnose"
    assert actions["A04_DIAGNOSE"]["display_stage"] == "gate"
    assert actions["A06_GATE"]["display_node"] == "gate"
    assert actions["A07_RESOLVE"]["display_node_by_status"] == {
        "ACCEPT": "accept",
        "KEEP": "keep",
        "ROLLBACK": "rollback",
        "blocked": "blocked",
        "failed": "blocked",
    }

    step_order = catalog["step_order"]
    assert step_order.index("A04_DIAGNOSE") < step_order.index("A05_OPTIMIZE")
    assert step_order.index("A05_OPTIMIZE") < step_order.index("A06_GATE")
    assert step_order.index("A06_GATE") < step_order.index("A07_RESOLVE")
