import json

from hydro_agent.replay.contracts import ReplayEvaluation
from hydro_agent.reporting.report import ReplayReportBuilder


def test_report_contains_traceable_scheme_snapshot_forecasts_metrics_and_research_evidence(tmp_path):
    hydrologic_evidence = {
        "window": "final_test",
        "quality": {
            "total_count": 3,
            "valid_count": 3,
            "dropped_count": 0,
            "coverage": 1.0,
            "dropped_by_reason": {},
        },
        "overall": {
            "name": "overall",
            "status": "available",
            "sample_count": 3,
            "start": "2025-05-08",
            "end": "2025-05-10",
            "metrics": {"nse": 0.3, "kge": 0.35},
            "notes": [],
        },
        "flow_regimes": {},
        "seasons": {},
        "years": {
            "2025": {
                "name": "2025",
                "status": "insufficient_data",
                "sample_count": 3,
                "metrics": {},
                "notes": ["requires_at_least=30"],
            }
        },
        "fdc": {
            "name": "fdc",
            "status": "insufficient_data",
            "sample_count": 3,
            "metrics": {},
            "notes": ["requires_at_least=20"],
        },
        "flood_events": [],
        "annual_stability": {
            "name": "annual_stability",
            "status": "insufficient_data",
            "sample_count": 0,
            "metrics": {},
            "notes": ["requires_at_least_years=2"],
        },
    }
    evaluation = ReplayEvaluation(
        task_id="task-1",
        scheme_id="scheme-frozen-1",
        observation_snapshot_id="snapshot-eval-truth",
        forecast_ids=("fc-1", "fc-2"),
        metrics={
            "NSE": 0.5,
            "KGE": 0.4,
            "MAE": 1.2,
            "Bias": -0.1,
            "rolling_NSE": 0.5,
            "continuous_NSE": 0.3,
        },
        rolling_metrics={"NSE": 0.5, "KGE": 0.4, "MAE": 1.2, "Bias": -0.1},
        lead_metrics={
            "lead_1": {"NSE": 0.5, "KGE": 0.4, "MAE": 1.2, "Bias": -0.1},
        },
        continuous_metrics={
            "NSE": 0.3,
            "KGE": 0.35,
            "PBIAS": -3.0,
            "RMSE": 1.8,
            "MAE": 1.4,
            "HighFlowMAE": 2.1,
            "PeakRatio": 0.98,
            "PeakTimingLagSteps": 1.0,
            "SampleCount": 30.0,
        },
        hydrologic_evidence=hydrologic_evidence,
        sample_counts={"lead_1": 3},
        forcing_mode="R",
        provenance={"source_scheme_id": "scheme-base"},
        agent_calibration={
            "artifacts": ["calibration-comparison.png", "calibration-comparison.json"],
            "trials": [
                {
                    "strategy_id": "xaj-water-balance-v1",
                    "development_gate": "ROLLBACK",
                    "baseline_nse": -6.315,
                    "candidate_nse": 0.782,
                    "base_primary": -1.317,
                    "candidate_primary": -11.411,
                    "gate_reasons": [
                        "lead_1_guardrail",
                        "lead_1_high_flow_guardrail",
                        "insufficient_absolute_skill",
                    ],
                    "parameter_delta": {"K": -0.25, "SM": 10.0},
                }
            ],
        },
    )
    report_builder = ReplayReportBuilder()
    json_path, md_path = report_builder.build(evaluation, tmp_path)
    payload = json.loads(json_path.read_text())
    assert payload["scheme_id"] == "scheme-frozen-1"
    assert payload["observation_snapshot_id"] == "snapshot-eval-truth"
    assert payload["forecast_ids"]
    assert payload["rolling_metrics"]["NSE"] == 0.5
    assert payload["continuous_metrics"]["NSE"] == 0.3
    assert payload["hydrologic_evidence"]["fdc"]["status"] == "insufficient_data"

    evidence_path = tmp_path / "research-evidence.json"
    assert evidence_path.is_file()
    persisted = json.loads(evidence_path.read_text())
    assert persisted["quality"]["coverage"] == 1.0
    assert persisted["overall"]["sample_count"] == 3
    assert persisted["annual_stability"]["status"] == "insufficient_data"

    text = md_path.read_text()
    assert "NSE" in text and "KGE" in text and "scheme-frozen-1" in text
    assert "Rolling Forecast Skill · final_test" in text
    assert "Continuous Simulation Skill · final_test" in text
    assert "Hydrologic Evidence · final_test" in text
    assert "research-evidence.json" in text
    assert "intentionally not averaged together" in text
    assert "智能体调参" in text
    assert "ROLLBACK 只决定最终是否采用候选" in text
    assert "calibration-comparison.png" in text
    assert "xaj-water-balance-v1" in text
    assert "率定窗 NSE" in text
    assert "`K`" in text
    assert "第 1 日预见期 NSE 下降超过允许值" in text
    assert "lead_1_guardrail" in text

    again_json, again_md = report_builder.build(evaluation, tmp_path / "again")
    assert again_json.read_bytes() == json_path.read_bytes()
    assert again_md.read_bytes() == md_path.read_bytes()
    assert (tmp_path / "again" / "research-evidence.json").read_bytes() == evidence_path.read_bytes()
