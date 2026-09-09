"""LangGraph subgraph: one node per GB/T 22482 §6.5 accuracy metric."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from hydro_agent.evaluation.gbt22482 import (
    GbtAccuracyConfig,
    GbtAccuracyReport,
    GbtMetricResult,
    HydroSeries,
    build_gbt_accuracy_report,
    evaluate_accuracy_rate,
    evaluate_dc_nse,
    evaluate_grd,
    evaluate_peak_flow,
    evaluate_peak_timing,
    evaluate_process,
    evaluate_runoff_volume,
    evaluate_scheme_grade,
    evaluate_timeliness,
    resolve_basin_class,
)


class GbtAccuracyState(TypedDict, total=False):
    series: HydroSeries
    config: GbtAccuracyConfig
    basin_class: str
    peak_flow: GbtMetricResult
    peak_timing: GbtMetricResult
    runoff_volume: GbtMetricResult
    process: GbtMetricResult
    dc_nse: GbtMetricResult
    accuracy_rate: GbtMetricResult
    grd: GbtMetricResult
    timeliness: GbtMetricResult
    scheme_grade: GbtMetricResult
    report: GbtAccuracyReport


def _basin(state: GbtAccuracyState):
    series = state["series"]
    cfg = state["config"]
    area = series.area_km2 if series.area_km2 is not None else cfg.area_km2
    return resolve_basin_class(area, cfg.basin_class)


def node_peak_flow(state: GbtAccuracyState) -> dict[str, Any]:
    return {"peak_flow": evaluate_peak_flow(state["series"], state["config"], _basin(state))}


def node_peak_timing(state: GbtAccuracyState) -> dict[str, Any]:
    return {"peak_timing": evaluate_peak_timing(state["series"], state["config"])}


def node_runoff_volume(state: GbtAccuracyState) -> dict[str, Any]:
    return {"runoff_volume": evaluate_runoff_volume(state["series"], state["config"])}


def node_process(state: GbtAccuracyState) -> dict[str, Any]:
    return {"process": evaluate_process(state["series"], state["config"])}


def node_dc_nse(state: GbtAccuracyState) -> dict[str, Any]:
    return {"dc_nse": evaluate_dc_nse(state["series"], state["config"])}


def node_accuracy_rate(state: GbtAccuracyState) -> dict[str, Any]:
    return {
        "accuracy_rate": evaluate_accuracy_rate(state["series"], state["config"], _basin(state))
    }


def node_grd(state: GbtAccuracyState) -> dict[str, Any]:
    return {"grd": evaluate_grd(state["series"], state["config"], _basin(state))}


def node_timeliness(state: GbtAccuracyState) -> dict[str, Any]:
    return {"timeliness": evaluate_timeliness(state["series"], state["config"])}


def node_aggregate(state: GbtAccuracyState) -> dict[str, Any]:
    cfg = state["config"]
    dc = state["dc_nse"]
    qr = state["accuracy_rate"]
    grade = evaluate_scheme_grade(dc, qr, cfg)
    metrics = (
        state["peak_flow"],
        state["peak_timing"],
        state["runoff_volume"],
        state["process"],
        dc,
        qr,
        state["grd"],
        state["timeliness"],
        grade,
    )
    basin = _basin(state)
    scheme = grade.grade if grade.grade in {"甲", "乙", "丙", "不合格"} else "不合格"
    from hydro_agent.evaluation.gbt22482 import grade_meets_min

    meets = grade_meets_min(scheme, cfg.min_scheme_grade)  # type: ignore[arg-type]
    report = GbtAccuracyReport(
        metrics=metrics,
        scheme_grade=scheme,  # type: ignore[arg-type]
        accuracy_rate=qr.value,
        dc=dc.value,
        meets_min_grade=meets,
        min_scheme_grade=cfg.min_scheme_grade,
        basin_class=basin,
        summary=(
            f"GB/T22482 scheme_grade={scheme} DC={dc.value} QR={qr.value} "
            f"basin={basin} meets_min={meets}"
        ),
    )
    return {"scheme_grade": grade, "report": report, "basin_class": basin}


def build_gbt_accuracy_graph():
    graph = StateGraph(GbtAccuracyState)
    graph.add_node("peak_flow", node_peak_flow)
    graph.add_node("peak_timing", node_peak_timing)
    graph.add_node("runoff_volume", node_runoff_volume)
    graph.add_node("process", node_process)
    graph.add_node("dc_nse", node_dc_nse)
    graph.add_node("accuracy_rate", node_accuracy_rate)
    graph.add_node("grd", node_grd)
    graph.add_node("timeliness", node_timeliness)
    graph.add_node("aggregate", node_aggregate)

    # Fan-out from START to metric nodes, then join at aggregate.
    for name in (
        "peak_flow",
        "peak_timing",
        "runoff_volume",
        "process",
        "dc_nse",
        "accuracy_rate",
        "grd",
        "timeliness",
    ):
        graph.add_edge(START, name)
        graph.add_edge(name, "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()


_GRAPH = None


def run_gbt_accuracy(series: HydroSeries, config: GbtAccuracyConfig) -> GbtAccuracyReport:
    """Execute the metric subgraph; falls back to direct report if LangGraph unavailable."""
    global _GRAPH
    try:
        if _GRAPH is None:
            _GRAPH = build_gbt_accuracy_graph()
        result = _GRAPH.invoke({"series": series, "config": config})
        report = result.get("report")
        if isinstance(report, GbtAccuracyReport):
            return report
    except Exception:
        pass
    return build_gbt_accuracy_report(series, config)
