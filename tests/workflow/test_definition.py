from hydro_agent.agent.contracts import ActionCode
from hydro_agent.agent.permissions import (
    CLOSEOUT_ACTIONS,
    EXPLORATORY_ACTIONS,
    IMPLEMENTED,
    PHASE_ACTIONS,
)
from hydro_agent.workflow.definition import current_binding, load_definition
from hydro_agent.workflow.generate import frontend_catalog
from hydro_agent.workflow.handlers import (
    assert_condition_implementations,
    assert_handlers_declared,
)


def test_v1_definition_matches_runtime_permissions():
    definition = load_definition()
    assert definition.workflow_id == "hydro-agent-calibration"
    assert definition.version == "1.0.0"
    assert definition.action("A06_DIAGNOSE").display_node == "diagnose"
    assert definition.display_node_for("A09_RESOLVE", "ACCEPT") == "accept"
    assert definition.display_node_for("A09_RESOLVE", "KEEP") == "keep"
    assert definition.display_node_for("A09_RESOLVE", "ROLLBACK") == "rollback"
    assert ActionCode.A02_REPAIR_DATA not in IMPLEMENTED
    assert ActionCode.A04_REBUILD_STATE not in IMPLEMENTED
    assert PHASE_ACTIONS["B"] == {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A03_VALIDATE_SCHEME,
        ActionCode.A05_FORECAST,
        ActionCode.A06_DIAGNOSE,
        ActionCode.A07_OPTIMIZE,
        ActionCode.A08_GATE,
        ActionCode.A09_RESOLVE,
        ActionCode.A10_FREEZE,
    }
    assert PHASE_ACTIONS["F"] == {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A03_VALIDATE_SCHEME,
        ActionCode.A05_FORECAST,
        ActionCode.A09_RESOLVE,
        ActionCode.A11_REPLAY,
    }
    assert PHASE_ACTIONS["E"] == {ActionCode.A12_EVALUATE_REPORT, ActionCode.A01_CHECK_DATA}
    assert EXPLORATORY_ACTIONS == {
        ActionCode.A01_CHECK_DATA,
        ActionCode.A03_VALIDATE_SCHEME,
        ActionCode.A05_FORECAST,
        ActionCode.A06_DIAGNOSE,
        ActionCode.A07_OPTIMIZE,
    }
    assert CLOSEOUT_ACTIONS == {
        ActionCode.A08_GATE,
        ActionCode.A09_RESOLVE,
        ActionCode.A10_FREEZE,
        ActionCode.A11_REPLAY,
        ActionCode.A12_EVALUATE_REPORT,
    }
    assert_handlers_declared(definition)
    assert_condition_implementations(definition)


def test_binding_hash_is_stable_and_prefixed():
    binding = current_binding()
    assert binding["workflow_id"] == "hydro-agent-calibration"
    assert binding["workflow_version"] == "1.0.0"
    assert binding["workflow_hash"].startswith("sha256:")
    assert len(binding["workflow_hash"]) == 7 + 64


def test_frontend_catalog_preserves_branching_workflow_metadata():
    definition = load_definition()
    binding = current_binding()
    catalog = frontend_catalog(definition, file_hash=binding["workflow_hash"])

    actions = catalog["actions"]
    assert actions["A06_DIAGNOSE"]["display_node"] == "diagnose"
    assert actions["A06_DIAGNOSE"]["display_stage"] == "gate"
    assert actions["A08_GATE"]["display_node"] == "gate"
    assert actions["A09_RESOLVE"]["display_node_by_status"] == {
        "ACCEPT": "accept",
        "KEEP": "keep",
        "ROLLBACK": "rollback",
    }

    step_order = catalog["step_order"]
    assert step_order.index("A06_DIAGNOSE") < step_order.index("A07_OPTIMIZE")
    assert step_order.index("A07_OPTIMIZE") < step_order.index("A08_GATE")
    assert step_order.index("A08_GATE") < step_order.index("A09_RESOLVE")
