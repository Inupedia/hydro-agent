import json

from hydro_agent.replay.contracts import ReplayEvaluation
from hydro_agent.reporting.report import ReplayReportBuilder


def test_report_contains_traceable_scheme_snapshot_forecasts_and_metrics(tmp_path):
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
        sample_counts={"lead_1": 3},
        forcing_mode="R",
        provenance={"source_scheme_id": "scheme-base"},
    )
    report_builder = ReplayReportBuilder()
    json_path, md_path = report_builder.build(evaluation, tmp_path)
    payload = json.loads(json_path.read_text())
    assert payload["scheme_id"] == "scheme-frozen-1"
    assert payload["observation_snapshot_id"] == "snapshot-eval-truth"
    assert payload["forecast_ids"]
    assert payload["rolling_metrics"]["NSE"] == 0.5
    assert payload["continuous_metrics"]["NSE"] == 0.3
    text = md_path.read_text()
    assert "NSE" in text and "KGE" in text and "scheme-frozen-1" in text
    assert "Rolling Forecast Skill · final_test" in text
    assert "Continuous Simulation Skill · final_test" in text
    assert "intentionally not averaged together" in text
    again_json, again_md = report_builder.build(evaluation, tmp_path / "again")
    assert again_json.read_bytes() == json_path.read_bytes()
    assert again_md.read_bytes() == md_path.read_bytes()
