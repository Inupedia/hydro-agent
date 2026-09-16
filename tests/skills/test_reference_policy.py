from hydro_agent.agent.contracts import (
    ActionCode,
    BudgetSummary,
    EvidenceSummary,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.skills import SkillRegistry
from hydro_agent.skills.reference_policy import references_for_view


def _view(**updates) -> WorldStateView:
    base = dict(
        task=TaskSummary(task_id="t", basin_id="yaogu", phase="B", forcing_mode="R"),
        model=ModelSummary(model_id="xaj", capabilities=("forecast", "calibrate")),
        scheme=SchemeSummary(scheme_id="s", status="base", content_hash="h"),
        permissions=PermissionSummary(safe_actions=(ActionCode.A05_OPTIMIZE,)),
        budget=BudgetSummary(
            agent_rounds_remaining=10,
            optimization_cycles_remaining=2,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
        hydro=HydroContext(),
    )
    base.update(updates)
    return WorldStateView(**base)


def test_xaj_calibration_references_follow_diagnosis_and_resolve_evidence():
    registry = SkillRegistry()
    skill = registry.get_loaded("xaj-calibration-diagnosis")
    view = _view(hydro=HydroContext(diagnosis={"recommended_param_groups": ["routing"]}))
    selected = references_for_view(skill, view)
    assert selected == (
        "references/xaj-calibration-workflow.md",
        "references/xaj-calibration-parameter-semantics.md",
        "references/xaj-routing-diagnosis-routing.md",
        "references/xaj-routing-diagnosis-recession-and-lag.md",
    )
    _, audit = registry.activate_with_manifest("xaj-calibration-diagnosis", reference_paths=selected)
    assert [item["path"] for item in audit["loaded_references"]] == list(selected)

    reviewed = view.model_copy(
        update={
            "hydro": HydroContext(diagnosis={"recommended_param_groups": ["runoff", "routing"]}),
            "evidence_summary": (
                EvidenceSummary(
                    evidence_id="resolve-evidence",
                    action=ActionCode.A07_RESOLVE,
                    status="KEEP",
                    new_information_hash="h2",
                ),
            ),
        }
    )
    reviewed_refs = references_for_view(skill, reviewed)
    assert "references/xaj-calibration-escalation.md" in reviewed_refs
    assert "references/xaj-runoff-generation-runoff-generation.md" in reviewed_refs
    assert "references/xaj-routing-diagnosis-routing.md" in reviewed_refs
    assert "references/xaj-water-balance-water-balance.md" not in reviewed_refs


def test_evidence_and_experiment_references_follow_model_and_budget():
    registry = SkillRegistry()
    evidence = registry.get_loaded("hydrologic-evidence-review")
    design = registry.get_loaded("calibration-experiment-design")

    openhydro = _view(
        model=ModelSummary(model_id="openhydronet", capabilities=("forecast",)),
        hydro=HydroContext(diagnosis={"note": "structure"}),
    )
    refs = references_for_view(evidence, openhydro)
    assert "references/hydro-error-diagnosis-metric-patterns.md" in refs
    assert "references/openhydronet-diagnosis-openhydronet-diagnosis.md" in refs

    tight = _view(
        budget=BudgetSummary(
            agent_rounds_remaining=1,
            optimization_cycles_remaining=1,
            max_agent_rounds=10,
            max_optimization_cycles=2,
        ),
        evidence_summary=(
            EvidenceSummary(
                evidence_id="opt",
                action=ActionCode.A05_OPTIMIZE,
                status="ok",
                new_information_hash="h",
            ),
        ),
    )
    design_refs = references_for_view(design, tight)
    assert "references/hydro-experiment-design-budget-allocation.md" in design_refs
    assert "references/hydro-experiment-design-experiment-strategies.md" in design_refs
