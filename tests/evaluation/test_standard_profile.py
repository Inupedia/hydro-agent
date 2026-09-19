from hydro_agent.evaluation.standard_profile import StandardEvaluationResult, not_evaluated_standard


def test_standard_profile_can_remain_not_evaluated_without_research_semantics():
    result = not_evaluated_standard(
        profile_id="operational_gbt",
        standard_id="GB/T 22482",
    )
    assert isinstance(result, StandardEvaluationResult)
    assert result.status == "not_evaluated"
    assert result.grade is None
