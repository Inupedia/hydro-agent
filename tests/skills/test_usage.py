from types import SimpleNamespace

from hydro_agent.skills.usage import build_skill_usage


def test_build_skill_usage_merges_snapshot_and_invocations():
    snapshot = {
        "sha256": "s" * 64,
        "skills": {
            "hydrologic-evidence-review": {
                "source": "builtin",
                "binding": {"activation_stages": ["diagnosis"], "activation_model_ids": []},
                "files": {"SKILL.md": {"sha256": "a" * 64, "data_b64": ""}},
            },
            "calibration-experiment-design": {
                "source": "builtin",
                "binding": {"activation_stages": ["experiment"], "activation_model_ids": []},
                "files": {"SKILL.md": {"sha256": "b" * 64, "data_b64": ""}},
            },
        },
    }
    decisions = [
        SimpleNamespace(
            decision_id="d1",
            round_number=2,
            action="A05_OPTIMIZE",
            model="calibration-scientist",
            activated_skills_json=[
                {
                    "skill_id": "hydrologic-evidence-review",
                    "skill_sha256": "a" * 64,
                    "output_contract": "EvidenceInterpretation",
                    "loaded_references": [{"path": "references/x.md", "sha256": "c" * 64}],
                },
                {
                    "skill_id": "calibration-experiment-design",
                    "skill_sha256": "b" * 64,
                    "output_contract": "CalibrationPlan",
                    "loaded_references": [],
                },
            ],
        )
    ]
    payload = build_skill_usage(task_id="task-1", snapshot=snapshot, decisions=decisions)
    assert payload["snapshot_sha256"] == "s" * 64
    assert payload["invocation_count"] == 2
    assert payload["usage_by_skill"][0]["invocation_count"] >= 1
    ids = {row["skill_id"] for row in payload["usage_by_skill"]}
    assert ids == {"hydrologic-evidence-review", "calibration-experiment-design"}
    assert payload["invocations"][0]["loaded_reference_count"] == 1
