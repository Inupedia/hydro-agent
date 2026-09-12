from hydro_agent.optimization.calibration_scientist import plan_from_diagnosis
from hydro_agent.optimization.search_evidence import analyze_search_boundaries


def test_local_search_boundary_is_not_mislabeled_as_absolute():
    evidence = analyze_search_boundaries(
        values={"K": 1.2},
        search_bounds={"K": (0.8, 1.2)},
        absolute_bounds={"K": (0.5, 1.5)},
    )

    assert evidence.local_hits == ("K",)
    assert evidence.absolute_hits == ()
    assert evidence.hits[0].side == "upper"
    assert evidence.hits[0].scope == "local"


def test_absolute_boundary_is_distinguished_from_local_window():
    evidence = analyze_search_boundaries(
        values={"K": 1.49},
        search_bounds={"K": (0.5, 1.5)},
        absolute_bounds={"K": (0.5, 1.5)},
    )

    assert evidence.local_hits == ()
    assert evidence.absolute_hits == ("K",)
    assert evidence.hits[0].scope == "absolute"


def test_local_boundary_advances_to_broader_but_still_bounded_strategy():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "水量偏差且上一轮局部窗口触边界",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "previous_strategy_id": "xaj-water-balance-v1",
            "recommended_param_groups": ["evap", "runoff"],
            "recommended_objective": "composite",
            "local_boundary_hits": ["K"],
            "metrics": {"pbias_percent": 18.0, "nse": 0.3},
        }
    )

    assert plan.strategy_id == "xaj-broadened-refine-v1"
    assert plan.local_scale == 0.65
    assert plan.parameter_groups == ("evap", "runoff")
    assert plan.search_adjustment == "broaden_within_absolute_bounds"
    assert "expert.local_boundary_can_broaden_within_bounds" in plan.knowledge_refs


def test_repeated_local_boundary_can_progress_to_global_absolute_window():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "扩大后的局部窗口仍触边界",
            "recommended_strategy_id": "xaj-hydro-composite-v1",
            "previous_strategy_id": "xaj-broadened-refine-v1",
            "recommended_param_groups": ["runoff"],
            "recommended_objective": "composite",
            "local_boundary_hits": ["B"],
            "metrics": {"nse": 0.3},
        }
    )

    assert plan.strategy_id == "xaj-bounded-v1"
    assert plan.search_scope == "global"
    assert plan.local_scale is None
    assert plan.parameter_groups == ("runoff",)


def test_absolute_boundary_never_expands_beyond_teacher_kernel_bounds():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "候选已触及绝对参数边界",
            "recommended_strategy_id": "xaj-water-balance-v1",
            "previous_strategy_id": "xaj-water-balance-v1",
            "recommended_param_groups": ["evap", "runoff"],
            "recommended_objective": "composite",
            "absolute_boundary_hits": ["K"],
            "metrics": {"pbias_percent": 18.0, "nse": 0.3},
        }
    )

    assert plan.strategy_id == "xaj-water-balance-v1"
    assert plan.search_adjustment == "hold_absolute_bounds"
    assert "expert.absolute_boundary_requires_diagnosis" in plan.knowledge_refs
    assert "禁止继续外扩" in plan.rationale
