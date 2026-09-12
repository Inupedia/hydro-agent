from dataclasses import dataclass
from datetime import date

from hydro_agent.knowledge.basin_priors import derive_basin_hydro_profile
from hydro_agent.knowledge.expert import ExpertKnowledgeRepository
from hydro_agent.optimization.calibration_scientist import plan_from_diagnosis


@dataclass(frozen=True)
class _Forcing:
    valid_date: date
    precipitation_mm_day: float
    pet_mm_day: float


@dataclass(frozen=True)
class _Flow:
    valid_date: date
    discharge_m3s: float


def test_external_expert_skill_is_seed_prior_not_normative():
    repo = ExpertKnowledgeRepository()
    source = repo.source()

    assert source["status"] == "seed_prior"
    assert source["authority"] == "advisory_only"
    assert source["provenance"]["source_license"] == "PolyForm Noncommercial License 1.0.0"
    assert source["provenance"]["reuse_policy"] == "conceptual_reimplementation_no_source_copy"

    advice = repo.advise({"metrics": {"nse": 0.4}})
    assert advice.is_normative is False


def test_water_balance_prior_refines_broad_plan_before_sceua():
    plan = plan_from_diagnosis(
        {
            "hypothesis": "MODEL",
            "phenomenon": "整体拟合不足且水量偏差较大",
            "recommended_strategy_id": "xaj-bounded-v1",
            "recommended_param_groups": ["evap", "runoff", "routing"],
            "recommended_objective": "nse",
            "metrics": {"nse": 0.42, "pbias_percent": 18.0},
        }
    )

    assert plan.parameter_groups == ("evap", "runoff")
    assert plan.objective == "composite"
    assert "expert.water_balance_first" in plan.knowledge_refs
    assert plan.optimizer == "sce-ua"
    assert plan.tunes_raw_parameter_vector is False


def test_negative_nse_is_warning_not_gate_override():
    repo = ExpertKnowledgeRepository()
    advice = repo.advise({"metrics": {"nse": -0.2, "pbias_percent": 2.0}})

    assert "expert.negative_skill_check_data_first" in advice.matched_rule_ids
    assert advice.prefer_recheck is True
    assert advice.recommended_param_groups is None
    assert advice.is_normative is False


def test_basin_attributes_are_profiled_as_advisory_context():
    repo = ExpertKnowledgeRepository()
    advice = repo.advise(
        {"metrics": {"nse": 0.55}},
        basin_attributes={
            "aridity": 0.62,
            "runoff_ratio": 0.41,
            "baseflow_index": 0.58,
            "frac_snow": 0.12,
            "climate_zone": "humid_cold",
        },
    )

    assert "expert.basin_attributes_are_priors" in advice.matched_rule_ids
    assert any("aridity=0.62" in note for note in advice.notes)


def test_derived_basin_profile_does_not_use_validation_future():
    forcing = (
        _Forcing(date(2000, 1, 1), 10.0, 5.0),
        _Forcing(date(2000, 1, 2), 10.0, 5.0),
        _Forcing(date(2000, 1, 3), 1000.0, 1000.0),
    )
    flow = (
        _Flow(date(2000, 1, 1), 1.0),
        _Flow(date(2000, 1, 2), 1.0),
        _Flow(date(2000, 1, 3), 1000.0),
    )

    profile = derive_basin_hydro_profile(
        forcing_rows=forcing,
        flow_rows=flow,
        area_km2=100.0,
        before_date=date(2000, 1, 3),
    )

    assert profile.aridity == 0.5
    # Two days * 1 m3/s => 1.728 mm runoff over 100 km2; P=20 mm.
    assert profile.runoff_ratio == 0.0864


def test_measured_evaporation_is_not_mislabeled_as_aridity():
    forcing = (
        _Forcing(date(2000, 1, 1), 10.0, 9.0),
        _Forcing(date(2000, 1, 2), 10.0, 9.0),
    )
    flow = (
        _Flow(date(2000, 1, 1), 1.0),
        _Flow(date(2000, 1, 2), 1.0),
    )

    profile = derive_basin_hydro_profile(
        forcing_rows=forcing,
        flow_rows=flow,
        area_km2=100.0,
        evaporation_is_potential=False,
    )

    assert profile.aridity is None
    assert profile.runoff_ratio == 0.0864
