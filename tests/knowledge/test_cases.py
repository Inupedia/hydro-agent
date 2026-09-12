from hydro_agent.knowledge import CalibrationCase, CalibrationCaseMemory, lesson_from_gate


def test_case_memory_round_trip_and_similarity(tmp_path):
    memory = CalibrationCaseMemory(tmp_path / "cases.jsonl")
    case = CalibrationCase(
        case_id="yaogu-001",
        basin_id="yaogu",
        hypothesis="MODEL",
        phenomenon="训练改善但独立验证不合格",
        strategy_id="xaj-bounded-v1",
        optimizer="sce-ua",
        param_groups=("runoff", "routing"),
        objective="nse",
        calibration_metrics={"nse": 0.6},
        validation_metrics={"nse": -0.2},
        gate_status="KEEP",
        parameter_delta={"B": 0.01},
        lesson=lesson_from_gate("KEEP"),
    )
    memory.append(case)

    assert memory.list() == (case,)
    assert memory.similar(hypothesis="MODEL") == (case,)
    assert memory.similar(param_groups=("routing",)) == (case,)
    assert memory.similar(hypothesis="TIMING") == ()
    assert "重新诊断" in case.lesson
