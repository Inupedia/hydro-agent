from hydro_agent.knowledge import CalibrationCase, CalibrationCaseMemory, lesson_from_gate


def test_case_memory_round_trip_and_similarity(tmp_path):
    memory = CalibrationCaseMemory(tmp_path / "cases.jsonl")
    case = CalibrationCase(
        case_id="yaogu-001",
        basin_id="yaogu",
        hypothesis="MODEL",
        phenomenon="训练改善但独立验证不合格",
        strategy_id="xaj-bounded-v1",
        optimizer="dds",
        param_groups=("runoff", "routing"),
        objective="nse",
        calibration_metrics={"nse": 0.6},
        validation_metrics={"nse": -0.2},
        gate_status="ACCEPT",
        adoption_status="ADOPT",
        qualification_status="UNQUALIFIED",
        parameter_delta={"B": 0.01},
        lesson=lesson_from_gate(
            "ACCEPT",
            adoption_status="ADOPT",
            qualification_status="UNQUALIFIED",
        ),
    )
    memory.append(case)

    assert memory.list() == (case,)
    assert memory.similar(hypothesis="MODEL") == (case,)
    assert memory.similar(param_groups=("routing",)) == (case,)
    assert memory.similar(hypothesis="TIMING") == ()
    assert "不能标记为达标正案例" in case.lesson


def test_legacy_case_json_keeps_backward_compatible_dual_gate_defaults():
    legacy = CalibrationCase.model_validate(
        {
            "case_id": "legacy-001",
            "basin_id": "yaogu",
            "hypothesis": "MODEL",
            "strategy_id": "xaj-bounded-v1",
            "optimizer": "sce-ua",
            "gate_status": "KEEP",
            "lesson": "legacy",
        }
    )
    assert legacy.adoption_status == "UNKNOWN"
    assert legacy.qualification_status == "NOT_EVALUATED"


def test_qualified_case_is_the_only_dual_gate_positive_lesson():
    lesson = lesson_from_gate(
        "ACCEPT",
        adoption_status="ADOPT",
        qualification_status="QUALIFIED",
    )
    assert "经验证的正案例" in lesson


def test_qualified_but_rolled_back_case_is_not_an_adoption_success():
    lesson = lesson_from_gate(
        "ROLLBACK",
        adoption_status="ROLLBACK",
        qualification_status="QUALIFIED",
    )
    assert "不得替换当前方案" in lesson
    assert "不标记为采用成功" in lesson
