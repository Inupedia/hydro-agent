from datetime import datetime

from hydro_agent.evaluation.gbt22482 import (
    GbtAccuracyConfig,
    HydroSeries,
    build_gbt_accuracy_report,
    grade_from_dc,
    grade_from_qr,
    grade_meets_min,
    peak_flow_permitted,
    resolve_basin_class,
)
from hydro_agent.graphs.gbt_accuracy import build_gbt_accuracy_graph, run_gbt_accuracy
from hydro_agent.optimization.contracts import EvaluationBundle, GatePolicy, LeadMetrics
from hydro_agent.optimization.gate import GateEvaluator


def _good_series() -> HydroSeries:
    # Nearly perfect match → high DC and QR.
    obs = (10.0, 40.0, 80.0, 50.0, 20.0, 12.0)
    sim = (10.5, 39.0, 78.0, 51.0, 21.0, 11.5)
    start = datetime(2020, 1, 1)
    times = tuple(datetime(2020, 1, 1 + i) for i in range(len(obs)))
    return HydroSeries(
        obs=obs,
        sim=sim,
        times=times,
        publish_time=start,
        area_km2=1500.0,
        dt_hours=24.0,
    )


def _poor_series() -> HydroSeries:
    obs = (10.0, 40.0, 80.0, 50.0, 20.0)
    sim = (2.0, 5.0, 8.0, 6.0, 3.0)
    return HydroSeries(obs=obs, sim=sim, area_km2=1500.0)


def test_basin_class_and_peak_permitted():
    assert resolve_basin_class(5000, "auto") == "gt3000"
    assert resolve_basin_class(1500, "auto") == "mid"
    p_large = peak_flow_permitted(100.0, "gt3000", GbtAccuracyConfig())
    p_mid = peak_flow_permitted(100.0, "mid", GbtAccuracyConfig())
    assert abs(p_large - 20.0) < 1e-9
    assert abs(p_mid - 30.0) < 1e-9


def test_table1_grades():
    cfg = GbtAccuracyConfig()
    assert grade_from_dc(0.91, cfg) == "甲"
    assert grade_from_dc(0.75, cfg) == "乙"
    assert grade_from_dc(0.55, cfg) == "丙"
    assert grade_from_dc(0.4, cfg) == "不合格"
    assert grade_from_qr(86, cfg) == "甲"
    assert grade_meets_min("乙", "丙")
    assert not grade_meets_min("不合格", "丙")


def test_build_report_good_series_meets_bing():
    report = build_gbt_accuracy_report(_good_series(), GbtAccuracyConfig(min_scheme_grade="丙"))
    ids = {m.metric_id for m in report.metrics}
    assert ids >= {
        "peak_flow",
        "peak_timing",
        "runoff_volume",
        "process",
        "dc_nse",
        "accuracy_rate",
        "grd",
        "timeliness",
        "scheme_grade",
    }
    assert report.meets_min_grade
    assert report.scheme_grade in {"甲", "乙", "丙"}


def test_build_report_poor_series_fails():
    report = build_gbt_accuracy_report(_poor_series(), GbtAccuracyConfig(min_scheme_grade="丙"))
    assert not report.meets_min_grade


def test_gbt_subgraph_runs_all_nodes():
    graph = build_gbt_accuracy_graph()
    out = graph.invoke({"series": _good_series(), "config": GbtAccuracyConfig()})
    assert out["report"].meets_min_grade
    assert out["peak_flow"].metric_id == "peak_flow"
    assert out["scheme_grade"].grade in {"甲", "乙", "丙"}


def test_run_gbt_accuracy_helper():
    report = run_gbt_accuracy(_good_series(), GbtAccuracyConfig())
    assert report.dc is not None


def _bundle(scheme_id, nses):
    leads = tuple(
        LeadMetrics(lead=i, nse=nses[i - 1], mae=1.0, bias=0.0, high_flow_mae=1.0)
        for i in (1, 2, 3)
    )
    return EvaluationBundle(
        scheme_id=scheme_id,
        leads=leads,
        primary_score=sum(nses) / 3.0,
    )


def test_gate_accepts_only_with_gbt_grade():
    base = _bundle("base", [0.2, 0.2, 0.2])
    cand = _bundle("cand", [0.35, 0.35, 0.35])  # improved but below 丙 DC
    policy = GatePolicy(
        min_primary_delta=0.01,
        max_single_lead_drop=0.02,
        max_high_flow_mae_relative_increase=0.05,
        accept_primary_floor=0.5,
        min_scheme_grade="丙",
        require_gbt_grade=True,
    )
    # Large relative gain alone must KEEP
    decision = GateEvaluator().evaluate(base, cand, policy, gbt_report=None)
    assert decision.status == "KEEP"

    good = build_gbt_accuracy_report(_good_series(), GbtAccuracyConfig(min_scheme_grade="丙"))
    decision_ok = GateEvaluator().evaluate(
        base,
        _bundle("cand2", [0.7, 0.7, 0.7]),
        policy,
        gbt_report=good,
    )
    assert decision_ok.status == "ACCEPT"
    assert "gbt_scheme_grade_ok" in decision_ok.reasons
