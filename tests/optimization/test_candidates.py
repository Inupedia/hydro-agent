import pytest

from hydro_agent.optimization.candidates import CandidateSchemeService, select_behavioral_candidates
from hydro_agent.persistence.database import Database
from hydro_agent.persistence.repository import HydroRepository

PARAMS = {
    "K": 0.75,
    "B": 0.25,
    "IM": 0.06,
    "UM": 20.0,
    "LM": 60.0,
    "DM": 40.0,
    "C": 0.16,
    "SM": 20.0,
    "EX": 1.2,
    "KI": 0.3,
    "KG": 0.4,
    "CS": 0.9,
    "L": 2.0,
    "CI": 0.8,
    "CG": 0.98,
}


@pytest.fixture
def seeded_repository(tmp_path):
    db = Database(f"sqlite+pysqlite:///{tmp_path}/hydro.db")
    db.create_schema()
    repo = HydroRepository(db)
    repo.create_task(task_id="task-1", basin_id="camels_13235000", phase="B", forcing_mode="R")
    repo.create_scheme(
        scheme_id="scheme-base",
        task_id="task-1",
        model_id="xaj",
        status="base",
        config={"model_id": "xaj", "warmup_days": 5, "parameters": PARAMS},
        content_hash="base-hash",
    )
    return repo


@pytest.fixture
def candidate_service(seeded_repository):
    return CandidateSchemeService(seeded_repository)


@pytest.fixture
def calibration_payload():
    return {
        "strategy_id": "xaj-bounded-v1",
        "candidate_parameters": dict(PARAMS, K=0.8),
    }


def test_candidate_registration_never_changes_base_scheme(
    seeded_repository, candidate_service, calibration_payload
):
    before = seeded_repository.get_scheme("scheme-base").content_hash
    candidate_id = candidate_service.register_candidate(
        base_scheme_id="scheme-base",
        action_run_id="cal-run-1",
        calibration_payload=calibration_payload,
    )
    after = seeded_repository.get_scheme("scheme-base").content_hash
    candidate = seeded_repository.get_scheme(candidate_id)
    assert before == after
    assert candidate.status == "candidate"
    assert candidate.scheme_id != "scheme-base"
    assert candidate.config_json["parameters"]["K"] == 0.8



def test_behavioral_set_keeps_near_optimal_parameter_distinct_candidates():
    result = select_behavioral_candidates(
        candidates=[
            {"candidate_id": "a", "objective_value": 0.86, "parameters": {"K": 0.8, "L": 2.0}},
            {"candidate_id": "b", "objective_value": 0.85, "parameters": {"K": 1.1, "L": 1.0}},
            {"candidate_id": "near-a", "objective_value": 0.855, "parameters": {"K": 0.801, "L": 2.001}},
            {"candidate_id": "c", "objective_value": 0.70, "parameters": {"K": 0.2, "L": 8.0}},
        ],
        objective_name="nse",
        parameter_bounds={"K": (0.0, 2.0), "L": (0.0, 10.0)},
        max_candidates=8,
        objective_tolerance=0.02,
        min_parameter_distance=0.05,
    )

    assert [item.candidate_id for item in result.items] == ["a", "b"]
    assert result.objective_best == pytest.approx(0.86)
    assert result.items[0].parameter_distance_from_best == pytest.approx(0.0)
    assert result.items[1].parameter_distance_from_best > 0.05
