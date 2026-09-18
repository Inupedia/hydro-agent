from fastapi.testclient import TestClient

from hydro_agent.api.app import create_app
from hydro_agent.experience.contracts import (
    ExperienceEntry,
    ExperienceEvidenceRef,
    ExperienceScope,
)


def _entry(experience_id, revision=1, confidence=0.85, status="active"):
    return ExperienceEntry(
        experience_id=experience_id,
        revision=revision,
        category="model",
        scope=ExperienceScope(model_ids=("xaj",), basin_ids=("basin-a",)),
        pattern={"peak_bias": "negative"},
        decision={"prefer_param_groups": ["routing"]},
        supporting_evidence=(
            ExperienceEvidenceRef(
                task_id="task-source",
                experiment_id="exp-1",
                evidence_id="ev-1",
            ),
        ),
        contradicting_evidence=(),
        confidence=confidence,
        status=status,
    )


def test_experience_api_exposes_summary_versions_and_provenance(app_dependencies):
    repo = app_dependencies.repository
    repo.append_experience_revision(_entry("EXP-XAJ-1"))
    repo.append_experience_revision(_entry("EXP-XAJ-1", revision=2, confidence=0.9))

    repo.create_experience_skill_version(
        version=1,
        parent_version=None,
        status="superseded",
        skill_hash="1" * 64,
        manifest={
            "source_experience_ids": ["EXP-XAJ-1"],
            "source_revisions": {"EXP-XAJ-1": 1},
        },
    )
    repo.create_experience_skill_version(
        version=2,
        parent_version=1,
        status="promoted",
        skill_hash="2" * 64,
        manifest={
            "source_experience_ids": ["EXP-XAJ-1", "EXP-XAJ-2"],
            "source_revisions": {"EXP-XAJ-1": 2, "EXP-XAJ-2": 1},
        },
        regression={"passed": True},
    )
    repo.append_experience_evolution_event(
        event_type="REINFORCE",
        reason="routing improvement repeated",
        task_id="task-source",
        experience_id="EXP-XAJ-1",
        from_revision=1,
        to_revision=2,
        evidence_refs=(
            ExperienceEvidenceRef(
                task_id="task-source",
                experiment_id="exp-1",
                evidence_id="ev-1",
            ),
        ),
    )

    app = create_app(app_dependencies)
    with TestClient(app) as client:
        summary = client.get("/api/experience/summary")
        assert summary.status_code == 200
        assert summary.json()["current_version"] == 2
        assert summary.json()["active_count"] == 1
        assert summary.json()["high_confidence_count"] == 1

        detail = client.get("/api/experience/entries/EXP-XAJ-1")
        assert detail.status_code == 200
        body = detail.json()
        assert body["revision"] == 2
        assert len(body["revisions"]) == 2
        assert body["supporting_evidence"][0]["evidence_id"] == "ev-1"

        versions = client.get("/api/experience/versions")
        assert versions.status_code == 200
        assert [item["version"] for item in versions.json()] == [1, 2]

        diff = client.get("/api/experience/versions/2/diff")
        assert diff.status_code == 200
        assert diff.json()["added"] == ["EXP-XAJ-2"]
        assert diff.json()["modified"] == ["EXP-XAJ-1"]

        evolution = client.get("/api/experience/evolution")
        assert evolution.json()[0]["evidence_refs"][0]["task_id"] == "task-source"

        regression = client.get("/api/experience/regression")
        assert regression.json()["items"][0]["version"] == 2

    app.state.executor.shutdown()


def test_experience_api_is_read_only(app_dependencies):
    app = create_app(app_dependencies)
    with TestClient(app) as client:
        assert client.post("/api/experience/entries", json={}).status_code == 405
        assert client.put("/api/experience/entries/EXP-1", json={}).status_code == 405
        assert client.delete("/api/experience/entries/EXP-1").status_code == 405
    app.state.executor.shutdown()
