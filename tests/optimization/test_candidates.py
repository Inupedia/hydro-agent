import pytest

from hydro_agent.optimization.candidates import CandidateSchemeService
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
