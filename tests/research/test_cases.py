from hydro_agent.research import lesson_from_gate


def test_case_memory_semantics_do_not_promote_unqualified_adoption():
    lesson = lesson_from_gate("ACCEPT", adoption_status="ADOPT", qualification_status="UNQUALIFIED")
    assert "尚未通过独立资格评价" in lesson
    assert "不能标记为达标正案例" in lesson
