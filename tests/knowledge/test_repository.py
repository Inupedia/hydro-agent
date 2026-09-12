from hydro_agent.knowledge import KnowledgeRepository


def test_gbt_standard_is_versioned_knowledge():
    repo = KnowledgeRepository()
    standard = repo.standard()
    assert standard["standard_id"] == "GB/T 22482-2026"
    assert standard["published_on"] == "2026-07-30"
    assert standard["effective_from"] == "2027-02-01"
    assert standard["replaces"] == "GB/T 22482-2008"
    assert standard["status"] == "published_not_effective"


def test_accuracy_profile_supplies_standard_thresholds():
    repo = KnowledgeRepository()
    meta = repo.gbt_accuracy_metadata(area_km2=1500.0)
    assert float(meta["grade_dc_jia"]) == 0.90
    assert float(meta["grade_dc_yi"]) == 0.70
    assert float(meta["grade_dc_bing"]) == 0.50
    assert float(meta["grade_qr_jia"]) == 85.0
    assert float(meta["grade_qr_yi"]) == 70.0
    assert float(meta["grade_qr_bing"]) == 60.0
    assert float(meta["peak_rel_error_mid"]) == 0.30
    assert float(meta["area_km2"]) == 1500.0


def test_project_gate_policy_is_separate_from_standard():
    repo = KnowledgeRepository()
    policy = repo.gate_defaults()
    assert policy["min_scheme_grade"] == "丙"
    assert policy["require_gbt_grade"] is True
    assert policy["fallback_without_standard_report"] == "KEEP"


def test_calibration_quality_rule_is_queryable():
    repo = KnowledgeRepository()
    rule = repo.rule("gbt22482-6.2.3-calibration-quality")
    assert rule["clause"] == "6.2.3"
    assert rule["kind"] == "calibration_governance"
    assert rule["standard_id"] == "GB/T 22482-2026"
