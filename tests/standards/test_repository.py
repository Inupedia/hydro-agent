from hydro_agent.standards import StandardRepository


def test_standard_repository_separates_standard_from_gate_policy():
    repository = StandardRepository()
    standard = repository.standard()
    policy = repository.policy()
    assert standard["standard_id"] == "GB/T 22482-2026"
    assert standard["status"] == "published_not_effective"
    assert policy["policy_id"] == "hydro-agent-research-v1"
    assert repository.gate_defaults()["require_gbt_grade"] is True
    assert float(repository.gbt_accuracy_metadata()["grade_dc_bing"]) == 0.5
    assert repository.grade_dc_bing() == 0.5
    assert repository.min_scheme_grade() == "丙"
    assert repository.gbt_accuracy_config().grade_dc_bing == 0.5
