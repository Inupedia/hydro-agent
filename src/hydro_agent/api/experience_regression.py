from __future__ import annotations

import copy
import uuid

from hydro_agent.experience.regression import ExperienceReplayOutcome
from hydro_agent.experience.snapshot import (
    build_version_experience_state_snapshot,
    verify_experience_state_snapshot,
)
from hydro_agent.skills.loader import parse_skill_md
from hydro_agent.skills.snapshot import build_snapshot, capture_package, verify_snapshot


class AppExperienceReplayRunner:
    """Re-run a historical calibration task with one frozen Experience Skill version.

    The replay clone uses the original task's frozen Skill Snapshot when available,
    replacing only calibration-experience. It runs through the normal AgentRuntime
    and is deleted after outcome extraction so regression jobs do not pollute the
    user task list.
    """

    def __init__(self, deps, *, version_store, cleanup: bool = True):
        self.deps = deps
        self.repository = deps.repository
        self.version_store = version_store
        self.cleanup = cleanup

    def run(
        self,
        *,
        task_id: str,
        experience_skill_version: int,
    ) -> ExperienceReplayOutcome:
        clone_id = self._clone_task(
            task_id,
            experience_skill_version=experience_skill_version,
        )
        try:
            runtime = (
                self.deps.runtime_for_task(clone_id)
                if self.deps.runtime_for_task is not None
                else self.deps.runtime_factory()
            )
            runtime.run_until_terminal(clone_id)
            return self._outcome(
                clone_id,
                source_task_id=task_id,
                experience_skill_version=experience_skill_version,
            )
        finally:
            if self.cleanup:
                self.deps.task_configs.pop(clone_id, None)
                try:
                    self.repository.delete_task(clone_id)
                except KeyError:
                    pass

    def _clone_task(
        self,
        task_id: str,
        *,
        experience_skill_version: int,
    ) -> str:
        source_task = self.repository.get_task(task_id)
        source_schemes = self.repository.list_schemes(task_id=task_id)
        if not source_schemes:
            raise ValueError(f"regression source task has no scheme: {task_id}")
        source_scheme = next(
            (scheme for scheme in source_schemes if scheme.status == "base"),
            source_schemes[0],
        )

        clone_id = _clone_id(task_id, experience_skill_version)
        self.repository.create_task(
            task_id=clone_id,
            basin_id=source_task.basin_id,
            phase="B",
            forcing_mode=source_task.forcing_mode,
            name=f"[experience-regression] {task_id} v{experience_skill_version}",
        )
        clone_scheme_id = f"{clone_id}--base"
        self.repository.create_scheme(
            scheme_id=clone_scheme_id,
            task_id=clone_id,
            model_id=source_scheme.model_id,
            status="base",
            config=copy.deepcopy(source_scheme.config_json or {}),
            content_hash=source_scheme.content_hash,
        )
        self.repository.ensure_task_state(
            clone_id,
            current_scheme_id=clone_scheme_id,
        )

        source_state = self.repository.ensure_task_state(task_id)
        source_snapshot = source_state.skill_snapshot_json
        if source_snapshot is None and self.deps.skills is not None:
            source_snapshot = self.deps.skills.freeze_for_task(task_id)
        snapshot = self._snapshot_with_experience(
            source_snapshot,
            experience_skill_version=experience_skill_version,
        )
        self.repository.set_skill_snapshot(clone_id, snapshot)

        version_row = self.repository.get_experience_skill_version(
            experience_skill_version
        )
        source_state_snapshot = source_state.experience_state_snapshot_json
        replay_state_snapshot = None
        if isinstance(source_state_snapshot, dict):
            verify_experience_state_snapshot(source_state_snapshot)
            if (
                int(source_state_snapshot["skill_version"])
                == experience_skill_version
                and str(source_state_snapshot["skill_hash"])
                == str(version_row.skill_hash)
            ):
                replay_state_snapshot = copy.deepcopy(source_state_snapshot)
        if replay_state_snapshot is None:
            replay_state_snapshot = build_version_experience_state_snapshot(
                self.repository,
                version_row,
            )
        self.repository.set_experience_state_snapshot(
            clone_id,
            replay_state_snapshot,
        )

        source_config = copy.deepcopy(self.deps.task_configs.get(task_id) or {})
        if not source_config:
            source_config = copy.deepcopy(
                (source_scheme.config_json or {}).get("workbench") or {}
            )
            source_config["model_id"] = source_scheme.model_id
            source_config["forcing_mode"] = source_task.forcing_mode
        self.deps.task_configs[clone_id] = source_config
        return clone_id

    def _snapshot_with_experience(
        self,
        source_snapshot: dict | None,
        *,
        experience_skill_version: int,
    ) -> dict:
        skills = {}
        if source_snapshot is not None:
            verify_snapshot(source_snapshot)
            skills = copy.deepcopy(source_snapshot["skills"])

        package_root = self.version_store.materialize(experience_skill_version)
        skill_md = (package_root / "SKILL.md").read_text(encoding="utf-8")
        loaded = parse_skill_md(
            skill_md,
            directory_name="calibration-experience",
            root=package_root,
        )
        skills["calibration-experience"] = {
            "source": "agent",
            "binding": {
                "activation_stages": list(loaded.meta_list("activation_stages")),
                "activation_model_ids": list(loaded.meta_list("activation_model_ids")),
            },
            "files": capture_package(package_root),
        }
        return build_snapshot(skills)

    def _outcome(
        self,
        clone_id: str,
        *,
        source_task_id: str,
        experience_skill_version: int,
    ) -> ExperienceReplayOutcome:
        task = self.repository.get_task(clone_id)
        state = self.repository.get_task_state(clone_id)
        evidence = self.repository.list_evidence(clone_id)

        signatures: list[str] = []
        failed_optimizations = 0
        guardrail_violations: list[str] = []
        quality_score = None

        for row in evidence:
            gates = dict(row.gates_json or {})
            if row.action == "A05_OPTIMIZE":
                if row.status == "failed":
                    failed_optimizations += 1
                signature = str(gates.get("experiment_signature") or "").strip()
                if signature:
                    signatures.append(signature)

            if row.action == "A06_GATE":
                raw_quality = row.metrics_json.get("candidate_primary") if row.metrics_json else None
                if isinstance(raw_quality, (int, float)):
                    quality_score = float(raw_quality)

            if row.action == "A10_EVALUATE_REPORT" and row.metrics_json:
                raw_nse = row.metrics_json.get("nse")
                if isinstance(raw_nse, (int, float)):
                    quality_score = float(raw_nse)

            if row.status in {"blocked", "failed"}:
                details = [
                    *(str(item) for item in (row.observations_json or ())),
                    *(f"{key}={value}" for key, value in gates.items()),
                ]
                details_text = " ".join(details).lower()
                for token in (
                    "guardrail",
                    "forbidden",
                    "illegal",
                    "leakage",
                    "constraint",
                ):
                    if token in details_text:
                        guardrail_violations.append(f"{row.action}:{token}")

        duplicate_count = len(signatures) - len(set(signatures))
        terminal_status = str(task.terminal_status or "")
        if not terminal_status:
            terminal_status = (
                "succeeded"
                if task.phase == "E" and not state.needs_follow_up and not state.paused
                else "paused"
                if state.paused
                else "incomplete"
            )

        return ExperienceReplayOutcome(
            task_id=source_task_id,
            experience_skill_version=experience_skill_version,
            terminal_status=terminal_status,
            optimization_cycles=state.optimization_cycles_used,
            repeated_failed_experiments=failed_optimizations + max(0, duplicate_count),
            quality_score=quality_score,
            guardrail_violations=tuple(sorted(set(guardrail_violations))),
        )


def _clone_id(task_id: str, version: int) -> str:
    suffix = uuid.uuid4().hex[:8]
    prefix = f"reg-{task_id}-v{version}-{suffix}"
    return prefix[:128]
