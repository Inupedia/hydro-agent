from __future__ import annotations

import json

from hydro_agent.agent.contracts import (
    MAX_AGENT_ROUNDS,
    MAX_OPTIMIZATION_CYCLES,
    BudgetSummary,
    EvidenceSummary,
    ExperienceContext,
    HydroContext,
    ModelSummary,
    PermissionSummary,
    SchemeSummary,
    TaskSummary,
    WorldStateView,
)
from hydro_agent.agent.permissions import PermissionGate
from hydro_agent.execution.hashing import sha256_bytes
from hydro_agent.experience.convergence import compute_convergence
from hydro_agent.experience.policy import ExperiencePolicy
from hydro_agent.experience.retrieval import ExperienceRetriever
from hydro_agent.experience.snapshot import (
    freeze_experience_state_for_task,
    verify_experience_state_snapshot,
)
from hydro_agent.models.registry import ModelRegistry, default_model_registry
from hydro_agent.optimization.campaign import rebuild_campaign_from_evidence
from hydro_agent.optimization.strategies import CalibrationStrategyRegistry
from hydro_agent.skills import CALIBRATION_EXPERIENCE_SKILL_ID, SkillRegistry
from hydro_agent.skills.loader import parse_skill_md
from hydro_agent.skills.snapshot import snapshot_file_bytes
from hydro_agent.workbench.validation_gate import latest_candidate_scheme_id


class WorldStateBuilder:
    def __init__(
        self,
        repository,
        *,
        model_id: str | None = None,
        capabilities: frozenset[str] | None = None,
        skills: SkillRegistry | None = None,
        strategies: CalibrationStrategyRegistry | None = None,
        model_registry: ModelRegistry | None = None,
        experience_retriever: ExperienceRetriever | None = None,
        experience_policy: ExperiencePolicy | None = None,
    ):
        self.repository = repository
        self.model_id = model_id
        self.capabilities = capabilities
        self.skills = skills or SkillRegistry(repository=repository)
        self.models = model_registry or default_model_registry()
        self.strategies = strategies or self.models.strategy_registry()
        self.experience_retriever = experience_retriever or ExperienceRetriever(repository)
        self.experience_policy = experience_policy or ExperiencePolicy()

    def build(self, task_id: str) -> WorldStateView:
        task = self.repository.get_task(task_id)
        from hydro_agent.workflow.definition import CURRENT_VERSION

        if task.workflow_version and task.workflow_version != CURRENT_VERSION:
            raise ValueError(
                f"task {task_id} is bound to workflow {task.workflow_version}; "
                f"current Agent runtime requires {CURRENT_VERSION}. Create a new task "
                "to use the continuous Action numbering."
            )
        state = self.repository.ensure_task_state(task_id)
        scheme = self.repository.get_scheme(state.current_scheme_id)
        evidence_rows = self.repository.list_evidence(task_id)
        evidence_summary = tuple(
            EvidenceSummary(
                evidence_id=row.evidence_id,
                action=row.action,
                status=row.status,
                new_information_hash=row.new_information_hash,
                observations=tuple(row.observations_json or ()),
                metrics={str(k): float(v) for k, v in dict(row.metrics_json or {}).items()},
                gates={str(k): str(v) for k, v in dict(row.gates_json or {}).items()},
            )
            for row in evidence_rows[-8:]
        )
        forecasts = [
            row
            for row in self.repository.list_forecasts(task_id)
            if row.scheme_id == scheme.scheme_id
        ]
        forecasts.sort(key=lambda row: (row.issue_time, row.forecast_id))
        latest_forecast = forecasts[-1] if forecasts else None
        current_params = dict((scheme.config_json or {}).get("parameters") or {})
        candidate = None
        candidate_id = latest_candidate_scheme_id(self.repository, task_id)
        if candidate_id and candidate_id != scheme.scheme_id:
            try:
                candidate = self.repository.get_scheme(candidate_id)
            except KeyError:
                candidate = None
        candidate_params = None
        parameter_delta: dict[str, float] = {}
        if candidate is not None:
            candidate_params = dict((candidate.config_json or {}).get("parameters") or {})
            for key, value in candidate_params.items():
                if key in current_params:
                    parameter_delta[key] = float(value) - float(current_params[key])
        diagnosis = {}
        for row in reversed(evidence_rows):
            if row.action == "A04_DIAGNOSE" and row.gates_json:
                diagnosis = dict(row.gates_json)
                diagnosis["metrics"] = {
                    str(k): float(v) for k, v in dict(row.metrics_json or {}).items()
                }
                for observation in row.observations_json or ():
                    prefix = "basin_attributes_json="
                    if not str(observation).startswith(prefix):
                        continue
                    try:
                        parsed = json.loads(str(observation)[len(prefix) :])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        diagnosis["basin_attributes"] = parsed
                    break
                break
        history = tuple(
            f"{row.action}:{row.status}:{';'.join((row.observations_json or [])[:2])}"
            for row in evidence_rows[-6:]
        )
        workbench = dict((scheme.config_json or {}).get("workbench") or {})
        raw_campaign_objective = str(workbench.get("calibration_objective") or "nse").strip()
        campaign_objective = (
            raw_campaign_objective
            if raw_campaign_objective in {"nse", "peak", "composite"}
            else "nse"
        )
        campaign = rebuild_campaign_from_evidence(
            evidence_rows,
            current_scheme_id=scheme.scheme_id,
            workbench=workbench,
        )
        raw_forbidden_datasets = workbench.get("forbidden_evidence_dataset_ids") or ()
        if isinstance(raw_forbidden_datasets, str):
            forbidden_evidence_dataset_ids = (raw_forbidden_datasets,)
        elif isinstance(raw_forbidden_datasets, (list, tuple)):
            forbidden_evidence_dataset_ids = tuple(
                str(item).strip() for item in raw_forbidden_datasets if str(item).strip()
            )
        else:
            forbidden_evidence_dataset_ids = ()
        model_id = str(scheme.model_id or self.model_id or "xaj")
        try:
            plugin = self.models.get(model_id)
            param_groups = tuple(plugin.descriptor.parameter_groups)
            validation_status = plugin.descriptor.validation_status
            implementation_name = plugin.descriptor.implementation_name
            limitations = plugin.descriptor.limitations
            capability_set = set(plugin.runtime_adapter.capabilities)
            if (
                not plugin.descriptor.supports_calibration
                and not bool(workbench.get("allow_unverified_model_calibration", False))
            ):
                capability_set.discard("calibrate")
            capabilities = tuple(sorted(capability_set))
        except KeyError:
            param_groups = ("evap", "runoff", "routing")
            validation_status = "unknown"
            implementation_name = model_id
            limitations = ()
            capabilities = tuple(
                sorted(self.capabilities or frozenset({"forecast", "calibrate", "validate"}))
            )
        strategy_ids = self.strategies.list_ids(model_id=model_id) or self.strategies.list_ids()
        strategy_ids = tuple(
            sid for sid in strategy_ids if not sid.endswith("-hydrologist-manual-v1")
        ) or strategy_ids

        raw_evolution_enabled = workbench.get("agent_evolution_enabled")
        agent_evolution_enabled = (
            bool(raw_evolution_enabled)
            if raw_evolution_enabled is not None
            else state.experience_state_snapshot_json is not None
        )
        experience = (
            self._experience_context(
                task_id=task_id,
                model_id=model_id,
                basin_id=task.basin_id,
                diagnosis=diagnosis,
            )
            if agent_evolution_enabled
            else ExperienceContext()
        )
        available_skills = self.skills.summaries_zh()
        skill_cards = tuple(self.skills.cards_for_prompt())
        if not agent_evolution_enabled:
            available_skills = tuple(
                item
                for item in available_skills
                if not item.startswith(f"{CALIBRATION_EXPERIENCE_SKILL_ID}:")
            )
            skill_cards = tuple(
                card
                for card in skill_cards
                if card.get("skill_id") != CALIBRATION_EXPERIENCE_SKILL_ID
            )
        hydro = HydroContext(
            current_parameters={k: float(v) for k, v in current_params.items()},
            candidate_parameters=candidate_params,
            parameter_delta=parameter_delta,
            latest_forecast_leads=(
                {int(k): float(v) for k, v in latest_forecast.lead_values_json.items()}
                if latest_forecast
                else {}
            ),
            available_skills=available_skills,
            available_strategies=strategy_ids,
            available_param_groups=param_groups,
            available_objectives=("nse", "peak", "composite"),
            campaign_objective=campaign_objective,
            campaign=campaign,
            allow_unverified_expert_priors=bool(
                workbench.get("allow_unverified_expert_priors", False)
            ),
            forbidden_evidence_dataset_ids=forbidden_evidence_dataset_ids,
            diagnosis=diagnosis,
            experiment_history=history,
            skill_cards=skill_cards,
            experience=experience,
        )
        allow_optimization = bool(workbench.get("allow_optimization", True))
        max_rounds = int(workbench.get("max_agent_decision_rounds") or MAX_AGENT_ROUNDS)
        max_opt = int(
            workbench["max_optimization_cycles"]
            if "max_optimization_cycles" in workbench
            else MAX_OPTIMIZATION_CYCLES
        )
        max_rounds = max(1, min(max_rounds, 100))
        max_opt = max(0, min(max_opt, 20))
        view = WorldStateView(
            task=TaskSummary(
                task_id=task.task_id,
                basin_id=task.basin_id,
                phase=task.phase,
                forcing_mode=task.forcing_mode,
                terminal_status=task.terminal_status,
                allow_optimization=allow_optimization,
                agent_evolution_enabled=agent_evolution_enabled,
            ),
            model=ModelSummary(
                model_id=model_id,
                capabilities=capabilities,
                validation_status=validation_status,
                implementation_name=implementation_name,
                limitations=limitations,
            ),
            scheme=SchemeSummary(
                scheme_id=scheme.scheme_id,
                status=scheme.status,
                content_hash=scheme.content_hash,
            ),
            permissions=PermissionSummary(safe_actions=(), paused=bool(state.paused)),
            budget=BudgetSummary(
                agent_rounds_remaining=max(0, max_rounds - state.agent_rounds_used),
                optimization_cycles_remaining=max(0, max_opt - state.optimization_cycles_used),
                max_agent_rounds=max_rounds,
                max_optimization_cycles=max_opt,
            ),
            evidence_summary=evidence_summary,
            latest_forecast_id=latest_forecast.forecast_id if latest_forecast else None,
            last_information_hash=state.last_information_hash,
            last_decision_fingerprint=state.last_decision_fingerprint,
            needs_follow_up=bool(state.needs_follow_up),
            hydro=hydro,
        )
        safe = PermissionGate().safe_actions(view)
        return view.model_copy(
            update={
                "permissions": PermissionSummary(safe_actions=safe, paused=view.permissions.paused)
            }
        )

    def _experience_context(
        self,
        *,
        task_id: str,
        model_id: str,
        basin_id: str,
        diagnosis: dict[str, object],
    ) -> ExperienceContext:
        state = self.repository.get_task_state(task_id)
        snapshot = state.skill_snapshot_json
        if snapshot is None:
            if self.skills.repository is self.repository:
                snapshot = self.skills.freeze_for_task(task_id)
            else:
                frozen_registry = SkillRegistry(
                    builtin_root=self.skills.builtin_root,
                    agent_root=self.skills.agent_root,
                    user_root=self.skills.user_root,
                    repository=self.repository,
                )
                snapshot = frozen_registry.freeze_for_task(task_id)

        events = self.repository.list_experience_evolution_events()
        convergence = compute_convergence(events)
        package = (snapshot.get("skills") or {}).get("calibration-experience")
        if not isinstance(package, dict) or package.get("source") != "agent":
            return ExperienceContext(
                status=convergence.status,
                exploration_level=0.75,
            )

        try:
            raw = snapshot_file_bytes(package["files"], "SKILL.md").decode("utf-8")
            loaded = parse_skill_md(raw, directory_name="calibration-experience")
            version = int(loaded.meta("hydro-agent-version"))
            version_row = self.repository.get_experience_skill_version(version)
        except (KeyError, TypeError, ValueError):
            return ExperienceContext(
                status=convergence.status,
                exploration_level=0.75,
            )

        state_snapshot = state.experience_state_snapshot_json
        if state_snapshot is None:
            state_snapshot = freeze_experience_state_for_task(
                self.repository,
                task_id,
                snapshot,
            )
        if state_snapshot is None:
            return ExperienceContext(
                status=convergence.status,
                exploration_level=0.75,
            )
        try:
            verify_experience_state_snapshot(state_snapshot)
            if (
                int(state_snapshot["skill_version"]) != version
                or str(state_snapshot["skill_hash"]) != str(version_row.skill_hash)
            ):
                raise ValueError("Experience State Snapshot does not match frozen Skill")
        except (KeyError, TypeError, ValueError):
            return ExperienceContext(
                status=convergence.status,
                exploration_level=0.75,
            )

        source_revisions = {
            str(experience_id): int(revision)
            for experience_id, revision in dict(
                state_snapshot.get("source_revisions") or {}
            ).items()
        }
        matches = self.experience_retriever.retrieve(
            model_id=model_id,
            basin_id=basin_id,
            diagnosis=diagnosis,
            revision_map=source_revisions,
        )
        _mode, exploration_level = self.experience_policy.choose_mode(matches)
        return ExperienceContext(
            skill_version=version,
            skill_hash=version_row.skill_hash,
            status=convergence.status,
            matches=matches,
            source_revisions=source_revisions,
            exploration_level=exploration_level,
        )


def world_state_hash(view: WorldStateView) -> str:
    return sha256_bytes(view.model_dump_json().encode("utf-8"))
