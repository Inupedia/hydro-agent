from hydro_agent.agent.contracts import ActionCode
from hydro_agent.agent.tool_catalog import TOOL_CATALOG, synthesize_tool_call


def test_every_runtime_action_has_a_tool_descriptor():
    assert set(TOOL_CATALOG) == set(ActionCode)
    assert len({item.tool_id for item in TOOL_CATALOG.values()}) == len(ActionCode)


def test_legacy_evidence_synthesizes_a_completed_tool_call():
    call = synthesize_tool_call(
        action="A05_OPTIMIZE",
        status="succeeded",
        observations=["optimizer=sce-ua", "model_evaluations=48"],
        metrics={"NSE": 0.781},
        strategy_id="xaj-bounded-v1",
        evidence_id="ev-1",
    )
    assert call is not None
    assert call["tool_id"] == "calibration.optimize"
    assert call["tool_name_zh"] == "参数优化工具"
    assert call["status"] == "completed"
    assert call["evidence_id"] == "ev-1"


def test_failed_and_blocked_tools_keep_their_real_status():
    failed = synthesize_tool_call(action="A03_FORECAST", status="failed", error="runner failed")
    blocked = synthesize_tool_call(action="A06_GATE", status="blocked")
    assert failed is not None and failed["status"] == "failed"
    assert failed["output_summary"] == {"error": "runner failed"}
    assert blocked is not None and blocked["status"] == "blocked"
