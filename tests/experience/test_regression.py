from types import SimpleNamespace

from hydro_agent.experience.regression import ExperienceRegressionSelector


class SelectionRepository:
    def __init__(self):
        self.tasks = [
            SimpleNamespace(
                task_id="task-a",
                basin_id="basin-a",
                phase="E",
                terminal_status=None,
            ),
            SimpleNamespace(
                task_id="task-b",
                basin_id="basin-b",
                phase="E",
                terminal_status=None,
            ),
            SimpleNamespace(
                task_id="task-hard",
                basin_id="basin-a",
                phase="E",
                terminal_status=None,
            ),
        ]
        self.evidence = {
            "task-a": [
                SimpleNamespace(
                    action="A06_GATE",
                    metrics_json={"peak_ratio": 0.8, "pbias_percent": 12.0},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                ),
                SimpleNamespace(
                    action="A10_EVALUATE_REPORT",
                    metrics_json={},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                ),
            ],
            "task-b": [
                SimpleNamespace(
                    action="A06_GATE",
                    metrics_json={"peak_timing_lag_days": 1.0, "high_flow_mae": 2.0},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                ),
                SimpleNamespace(
                    action="A10_EVALUATE_REPORT",
                    metrics_json={},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                ),
            ],
            "task-hard": [
                SimpleNamespace(
                    action="A06_GATE",
                    metrics_json={"peak_ratio": 1.2},
                    gates_json={"gate_status": "ROLLBACK"},
                    observations_json=[],
                    status="ROLLBACK",
                ),
                SimpleNamespace(
                    action="A10_EVALUATE_REPORT",
                    metrics_json={},
                    gates_json={},
                    observations_json=[],
                    status="succeeded",
                ),
            ],
        }

    def list_tasks(self):
        return self.tasks

    def get_task_state(self, task_id):
        return SimpleNamespace(paused=False, needs_follow_up=False)

    def list_schemes(self, task_id=None):
        return [SimpleNamespace(scheme_id=f"{task_id}-scheme")]

    def list_evidence(self, task_id):
        return self.evidence[task_id]

    def list_agent_decisions(self, task_id):
        version = 3 if task_id == "task-hard" else 2
        return [SimpleNamespace(experience_audit_json={"skill_version": version})]


def test_regression_selector_covers_tags_and_prioritizes_hard_cases():
    selected = ExperienceRegressionSelector().select(
        SelectionRepository(),
        limit_per_tag=1,
    )

    assert selected.cases[0].task_id == "task-hard"
    assert selected.cases[0].hard_case is True
    assert selected.cases[0].baseline_version == 3

    by_task = {case.task_id: case for case in selected.cases}
    assert "peak-under" in by_task["task-a"].tags
    assert "volume-bias" in by_task["task-a"].tags
    assert "timing-late" in by_task["task-b"].tags
    assert "high-flow" in by_task["task-b"].tags
    assert "peak-over" in by_task["task-hard"].tags
    assert all(any(tag.startswith("basin:") for tag in case.tags) for case in selected.cases)



def test_regression_selector_skips_unreplayable_or_incomplete_tasks(tmp_path):
    from hydro_agent.agent.contracts import ActionCode, EvidencePacket
    from hydro_agent.persistence.database import Database
    from hydro_agent.persistence.repository import HydroRepository

    db = Database(f"sqlite+pysqlite:///{tmp_path}/selector-validity.db")
    db.create_schema()
    repository = HydroRepository(db)

    repository.create_task(
        task_id="no-scheme",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
    )

    repository.create_task(
        task_id="incomplete",
        basin_id="basin-a",
        phase="E",
        forcing_mode="R",
    )
    repository.create_scheme(
        scheme_id="incomplete-base",
        task_id="incomplete",
        model_id="xaj",
        status="base",
        config={"parameters": {}},
        content_hash="incomplete-hash",
    )
    repository.ensure_task_state("incomplete", current_scheme_id="incomplete-base")
    repository.update_task_state("incomplete", needs_follow_up=False)

    repository.create_task(
        task_id="valid",
        basin_id="basin-b",
        phase="E",
        forcing_mode="R",
    )
    repository.create_scheme(
        scheme_id="valid-base",
        task_id="valid",
        model_id="xaj",
        status="base",
        config={"parameters": {}},
        content_hash="valid-hash",
    )
    repository.ensure_task_state("valid", current_scheme_id="valid-base")
    repository.update_task_state("valid", needs_follow_up=False)
    repository.add_evidence(
        EvidencePacket(
            evidence_id="valid-final",
            task_id="valid",
            action=ActionCode.A10_EVALUATE_REPORT,
            status="succeeded",
            metrics={"nse": 0.7},
            new_information_hash="valid-final-hash",
        )
    )

    selected = ExperienceRegressionSelector().select(repository)

    assert [case.task_id for case in selected.cases] == ["valid"]


def test_regression_service_preserves_per_case_deltas():
    from hydro_agent.experience.regression import (
        ExperienceRegressionService,
        ExperienceReplayOutcome,
        RegressionCase,
    )

    class ScriptedRunner:
        def __init__(self):
            self.outcomes = {
                ("task-a", 3): ExperienceReplayOutcome(
                    task_id="task-a",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=4,
                    repeated_failed_experiments=2,
                    quality_score=0.72,
                ),
                ("task-a", 4): ExperienceReplayOutcome(
                    task_id="task-a",
                    experience_skill_version=4,
                    terminal_status="succeeded",
                    optimization_cycles=3,
                    repeated_failed_experiments=1,
                    quality_score=0.74,
                ),
                ("task-hard", 3): ExperienceReplayOutcome(
                    task_id="task-hard",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=5,
                    repeated_failed_experiments=1,
                    quality_score=0.68,
                ),
                ("task-hard", 4): ExperienceReplayOutcome(
                    task_id="task-hard",
                    experience_skill_version=4,
                    terminal_status="failed",
                    optimization_cycles=5,
                    repeated_failed_experiments=1,
                    quality_score=0.60,
                    guardrail_violations=("illegal_group",),
                ),
            }

        def run(self, *, task_id, experience_skill_version):
            return self.outcomes[(task_id, experience_skill_version)]

    comparison = ExperienceRegressionService(ScriptedRunner()).compare(
        current_version=3,
        candidate_version=4,
        cases=(
            RegressionCase(task_id="task-a", tags=("peak-under",)),
            RegressionCase(task_id="task-hard", tags=("peak-over",), hard_case=True),
        ),
    )

    assert comparison.cases[0].repeated_failure_delta == -1
    assert comparison.cases[0].quality_delta == 0.02
    assert comparison.cases[1].case.hard_case is True
    assert comparison.cases[1].candidate.terminal_status == "failed"



def _comparison(*, hard_failure=False, quality_delta=0.0, new_violation=False, repeated_delta=0):
    from hydro_agent.experience.regression import (
        ExperienceReplayOutcome,
        RegressionCase,
        RegressionCaseComparison,
        RegressionComparison,
    )

    current_failed = 2
    candidate_failed = max(0, current_failed + repeated_delta)
    return RegressionComparison(
        current_version=3,
        candidate_version=4,
        cases=(
            RegressionCaseComparison(
                case=RegressionCase(
                    task_id="hard" if hard_failure else "ordinary",
                    tags=("peak-under",),
                    hard_case=hard_failure,
                ),
                current=ExperienceReplayOutcome(
                    task_id="hard" if hard_failure else "ordinary",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=4,
                    repeated_failed_experiments=current_failed,
                    quality_score=0.70,
                ),
                candidate=ExperienceReplayOutcome(
                    task_id="hard" if hard_failure else "ordinary",
                    experience_skill_version=4,
                    terminal_status="failed" if hard_failure else "succeeded",
                    optimization_cycles=3,
                    repeated_failed_experiments=candidate_failed,
                    quality_score=0.70 + quality_delta,
                    guardrail_violations=(("new_violation",) if new_violation else ()),
                ),
            ),
        ),
    )


def test_promotion_gate_rejects_hard_case_regression():
    from hydro_agent.experience.promotion import PromotionGate

    decision = PromotionGate().evaluate(_comparison(hard_failure=True))
    assert decision.accepted is False
    assert any(reason.startswith("HARD_CASE_REGRESSION") for reason in decision.reasons)


def test_promotion_gate_rejects_quality_and_guardrail_regression():
    from hydro_agent.experience.promotion import PromotionGate

    quality = PromotionGate(quality_tolerance=0.01).evaluate(
        _comparison(quality_delta=-0.03)
    )
    guardrail = PromotionGate().evaluate(_comparison(new_violation=True))

    assert quality.accepted is False
    assert any(reason.startswith("QUALITY_REGRESSION") for reason in quality.reasons)
    assert guardrail.accepted is False
    assert any(reason.startswith("NEW_GUARDRAIL_VIOLATION") for reason in guardrail.reasons)


def test_promotion_gate_rejects_ordinary_terminal_regression():
    from hydro_agent.experience.promotion import PromotionGate
    from hydro_agent.experience.regression import (
        ExperienceReplayOutcome,
        RegressionCase,
        RegressionCaseComparison,
        RegressionComparison,
    )

    comparison = RegressionComparison(
        current_version=3,
        candidate_version=4,
        cases=(
            RegressionCaseComparison(
                case=RegressionCase(task_id="ordinary", tags=("basin:a",)),
                current=ExperienceReplayOutcome(
                    task_id="ordinary",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=2,
                    repeated_failed_experiments=0,
                    quality_score=0.8,
                ),
                candidate=ExperienceReplayOutcome(
                    task_id="ordinary",
                    experience_skill_version=4,
                    terminal_status="failed",
                    optimization_cycles=2,
                    repeated_failed_experiments=0,
                    quality_score=None,
                ),
            ),
        ),
    )

    decision = PromotionGate().evaluate(comparison)

    assert decision.accepted is False
    assert "TERMINAL_STATUS_REGRESSION:ordinary" in decision.reasons
    assert "QUALITY_MISSING:ordinary" in decision.reasons


def test_promotion_gate_rejects_missing_candidate_quality():
    from hydro_agent.experience.promotion import PromotionGate
    from hydro_agent.experience.regression import (
        ExperienceReplayOutcome,
        RegressionCase,
        RegressionCaseComparison,
        RegressionComparison,
    )

    comparison = RegressionComparison(
        current_version=3,
        candidate_version=4,
        cases=(
            RegressionCaseComparison(
                case=RegressionCase(task_id="quality", tags=("basin:a",)),
                current=ExperienceReplayOutcome(
                    task_id="quality",
                    experience_skill_version=3,
                    terminal_status="succeeded",
                    optimization_cycles=2,
                    repeated_failed_experiments=0,
                    quality_score=0.8,
                ),
                candidate=ExperienceReplayOutcome(
                    task_id="quality",
                    experience_skill_version=4,
                    terminal_status="succeeded",
                    optimization_cycles=2,
                    repeated_failed_experiments=0,
                    quality_score=None,
                ),
            ),
        ),
    )

    decision = PromotionGate().evaluate(comparison)

    assert decision.accepted is False
    assert decision.reasons == ("QUALITY_MISSING:quality",)


def test_promotion_gate_rejects_repeated_failure_increase():
    from hydro_agent.experience.promotion import PromotionGate

    decision = PromotionGate().evaluate(
        _comparison(quality_delta=0.0, repeated_delta=10)
    )

    assert decision.accepted is False
    assert any(
        reason.startswith("REPEATED_FAILURE_REGRESSION:ordinary:+10")
        for reason in decision.reasons
    )


def test_promotion_gate_accepts_non_degrading_candidate_with_fewer_failures():
    from hydro_agent.experience.promotion import PromotionGate

    decision = PromotionGate().evaluate(
        _comparison(quality_delta=0.01, repeated_delta=-1)
    )

    assert decision.accepted is True
    assert decision.reasons == ("NON_DEGRADING", "REPEATED_FAILURE_REDUCTION")



def test_app_replay_runner_overrides_experience_snapshot_and_cleans_clone(tmp_path):
    from types import SimpleNamespace

    from hydro_agent.api.experience_regression import AppExperienceReplayRunner
    from hydro_agent.experience.compiler import ExperienceSkillCompiler
    from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope
    from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
    from hydro_agent.persistence.database import Database
    from hydro_agent.persistence.repository import HydroRepository
    from hydro_agent.skills.snapshot import snapshot_file_bytes

    db = Database(f"sqlite+pysqlite:///{tmp_path}/app-replay.db")
    db.create_schema()
    repository = HydroRepository(db)
    repository.create_task(
        task_id="source-task",
        basin_id="basin-a",
        phase="B",
        forcing_mode="R",
    )
    repository.create_scheme(
        scheme_id="source-base",
        task_id="source-task",
        model_id="xaj",
        status="base",
        config={"parameters": {"K": 0.7}, "workbench": {}},
        content_hash="source-hash",
    )
    repository.ensure_task_state("source-task", current_scheme_id="source-base")

    exp = ExperienceEntry(
        experience_id="EXP-RUN",
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=0.8,
        status="active",
    )
    repository.append_experience_revision(exp)
    store = ExperienceSkillVersionStore(tmp_path / "versions", repository=repository)
    compiled = ExperienceSkillCompiler().compile(1, (exp,))
    store.create_candidate(compiled)
    store.promote(1)

    seen = {}

    class Runtime:
        def run_until_terminal(self, clone_id):
            state = repository.get_task_state(clone_id)
            snapshot = state.skill_snapshot_json
            raw = snapshot_file_bytes(
                snapshot["skills"]["calibration-experience"]["files"],
                "SKILL.md",
            ).decode("utf-8")
            seen["clone_id"] = clone_id
            seen["skill_md"] = raw
            repository.set_task_phase(clone_id, "F")
            repository.set_task_phase(clone_id, "E")
            repository.update_task_state(clone_id, needs_follow_up=False)

    deps = SimpleNamespace(
        repository=repository,
        runtime_for_task=None,
        runtime_factory=lambda: Runtime(),
        task_configs={"source-task": {"model_id": "xaj"}},
        skills=None,
    )
    outcome = AppExperienceReplayRunner(
        deps,
        version_store=store,
        cleanup=True,
    ).run(
        task_id="source-task",
        experience_skill_version=1,
    )

    assert 'hydro-agent-version: "1"' in seen["skill_md"]
    assert outcome.task_id == "source-task"
    assert outcome.terminal_status == "succeeded"
    try:
        repository.get_task(seen["clone_id"])
    except KeyError:
        pass
    else:
        raise AssertionError("regression clone should be cleaned")



def test_rejected_candidate_restores_promoted_experience_structure(tmp_path):
    from hydro_agent.experience.compiler import ExperienceSkillCompiler
    from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope
    from hydro_agent.experience.diff import ExperienceDiff
    from hydro_agent.experience.promotion import ExperiencePromotionService
    from hydro_agent.experience.reflection import ExperienceDiffApplier
    from hydro_agent.experience.regression import (
        ExperienceRegressionService,
        ExperienceRegressionSet,
        ExperienceReplayOutcome,
        RegressionCase,
    )
    from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
    from hydro_agent.persistence.database import Database
    from hydro_agent.persistence.repository import HydroRepository

    db = Database(f"sqlite+pysqlite:///{tmp_path}/rejected-rollback.db")
    db.create_schema()
    repository = HydroRepository(db)
    parent = ExperienceEntry(
        experience_id="EXP-PARENT",
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={"hypothesis": "MODEL"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=0.8,
        status="active",
    )
    repository.append_experience_revision(parent)

    store = ExperienceSkillVersionStore(tmp_path / "store", repository=repository)
    compiler = ExperienceSkillCompiler()
    store.create_candidate(compiler.compile(1, (parent,)))
    store.promote(1, regression={"passed": True})

    child_wet = parent.model_copy(
        update={
            "experience_id": "EXP-WET",
            "revision": 1,
            "scope": ExperienceScope(
                model_ids=("xaj",),
                basin_ids=("basin-a",),
            ),
            "pattern": {"hypothesis": "MODEL", "regime": "wet"},
            "source_hash": None,
        }
    )
    child_dry = child_wet.model_copy(
        update={
            "experience_id": "EXP-DRY",
            "pattern": {"hypothesis": "MODEL", "regime": "dry"},
        }
    )
    split = ExperienceDiff(
        operation="SPLIT",
        experience_id="EXP-PARENT",
        proposals=(child_wet, child_dry),
        reason="regimes diverged",
    )
    applied = ExperienceDiffApplier(repository).apply("task-structural", (split,))
    assert applied.structural_change is True
    assert {entry.experience_id for entry in repository.list_active_experiences()} == {
        "EXP-WET",
        "EXP-DRY",
    }

    candidate = compiler.compile(2, repository.list_active_experiences())
    store.create_candidate(candidate)

    class Selector:
        def select(self, repository):
            return ExperienceRegressionSet(
                cases=(
                    RegressionCase(
                        task_id="task-hard",
                        tags=("peak-over",),
                        hard_case=True,
                    ),
                )
            )

    class HardRegressionRunner:
        def run(self, *, task_id, experience_skill_version):
            return ExperienceReplayOutcome(
                task_id=task_id,
                experience_skill_version=experience_skill_version,
                terminal_status=(
                    "succeeded" if experience_skill_version == 1 else "failed"
                ),
                optimization_cycles=4,
                repeated_failed_experiments=1,
                quality_score=0.70 if experience_skill_version == 1 else 0.60,
            )

    service = ExperiencePromotionService(
        repository,
        version_store=store,
        regression_service=ExperienceRegressionService(HardRegressionRunner()),
        selector=Selector(),
    )
    decision = service.validate_and_promote(2)

    assert decision.accepted is False
    assert any(
        reason.startswith("HARD_CASE_REGRESSION")
        for reason in decision.reasons
    )
    assert repository.get_experience_skill_version(2).status == "rejected"
    assert repository.get_current_experience_skill_version().version == 1

    active = repository.list_active_experiences()
    assert [entry.experience_id for entry in active] == ["EXP-PARENT"]
    restored = repository.get_experience("EXP-PARENT")
    assert restored.revision == 3
    assert restored.status == "active"
    assert repository.get_experience("EXP-WET").status == "rejected"
    assert repository.get_experience("EXP-DRY").status == "rejected"

    reject_events = [
        event
        for event in repository.list_experience_evolution_events()
        if event.event_type == "REJECT"
    ]
    assert len(reject_events) == 1
    assert reject_events[0].version_before == 1
    assert reject_events[0].version_after == 2



def test_promotion_excludes_candidate_source_tasks_from_regression():
    from types import SimpleNamespace

    from hydro_agent.experience.promotion import (
        ExperiencePromotionService,
        PromotionDecision,
    )
    from hydro_agent.experience.regression import (
        ExperienceRegressionSet,
        RegressionCase,
        RegressionComparison,
    )

    candidate = SimpleNamespace(
        version=2,
        status="candidate",
        manifest_json={
            "structural_changes": [
                {
                    "operation": "CREATE",
                    "evidence_refs": [
                        {"task_id": "task-source", "evidence_id": "ev-source"}
                    ],
                }
            ]
        },
    )
    current = SimpleNamespace(version=1)

    class Repository:
        def get_experience_skill_version(self, version):
            assert version == 2
            return candidate

        def get_current_experience_skill_version(self):
            return current

    class Selector:
        def select(self, repository):
            return ExperienceRegressionSet(
                cases=(
                    RegressionCase(task_id="task-source", tags=("peak-under",)),
                    RegressionCase(task_id="task-history", tags=("peak-under",)),
                )
            )

    seen = {}

    class Regression:
        def compare(self, *, current_version, candidate_version, cases):
            seen["cases"] = tuple(case.task_id for case in cases.cases)
            return RegressionComparison(
                current_version=current_version,
                candidate_version=candidate_version,
                cases=(),
            )

    class AcceptGate:
        def evaluate(self, comparison):
            return PromotionDecision(accepted=True, reasons=("TEST_ACCEPT",))

    class Store:
        def promote(self, version, *, regression=None):
            seen["promoted"] = version
            seen["regression"] = regression

    decision = ExperiencePromotionService(
        Repository(),
        version_store=Store(),
        regression_service=Regression(),
        selector=Selector(),
        gate=AcceptGate(),
    ).validate_and_promote(2)

    assert seen["cases"] == ("task-history",)
    assert seen["promoted"] == 2
    assert decision.accepted is True



def test_insufficient_regression_keeps_candidate_quarantined(tmp_path):
    from hydro_agent.experience.compiler import ExperienceSkillCompiler
    from hydro_agent.experience.contracts import ExperienceEntry, ExperienceScope
    from hydro_agent.experience.promotion import ExperiencePromotionService
    from hydro_agent.experience.regression import ExperienceRegressionService
    from hydro_agent.experience.skill_versions import ExperienceSkillVersionStore
    from hydro_agent.persistence.database import Database
    from hydro_agent.persistence.repository import HydroRepository

    db = Database(f"sqlite+pysqlite:///{tmp_path}/pending-candidate.db")
    db.create_schema()
    repository = HydroRepository(db)
    store = ExperienceSkillVersionStore(tmp_path / "pending-store", repository=repository)
    compiler = ExperienceSkillCompiler()

    store.create_candidate(compiler.compile(1, ()))
    store.promote(1, regression={"passed": True})

    proposal = ExperienceEntry(
        experience_id="EXP-PENDING",
        revision=1,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={"hypothesis": "MODEL"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(),
        contradicting_evidence=(),
        confidence=0.65,
        status="active",
    )
    repository.append_experience_revision(proposal)
    store.create_candidate(
        compiler.compile(2, (proposal,)),
        structural_changes=(
            {
                "operation": "CREATE",
                "experience_id": None,
                "source_ids": [],
                "proposal_ids": ["EXP-PENDING"],
                "reason": "new rule",
                "evidence_refs": [{"task_id": "task-source"}],
            },
        ),
    )

    class NoReplay:
        def run(self, *, task_id, experience_skill_version):
            raise AssertionError("empty regression set should not invoke replay")

    decision = ExperiencePromotionService(
        repository,
        version_store=store,
        regression_service=ExperienceRegressionService(NoReplay()),
    ).validate_and_promote(2)

    assert decision.accepted is False
    assert decision.reasons == ("INSUFFICIENT_REGRESSION_CASES",)
    pending = repository.get_experience_skill_version(2)
    assert pending.status == "candidate"
    assert pending.regression_json["promotion_decision"]["accepted"] is False
    assert repository.get_experience("EXP-PENDING").status == "active"
    assert not any(
        event.event_type == "REJECT"
        for event in repository.list_experience_evolution_events()
    )
