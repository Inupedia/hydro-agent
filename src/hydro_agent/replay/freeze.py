from __future__ import annotations

import copy
import json

from hydro_agent.agent.contracts import MAX_AGENT_ROUNDS, MAX_OPTIMIZATION_CYCLES
from hydro_agent.execution.hashing import sha256_bytes


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class FreezeService:
    def __init__(
        self, repository, *, gate_policy: dict | None = None, budget_summary: dict | None = None
    ):
        self.repository = repository
        self.gate_policy = gate_policy or {
            "min_primary_delta": 0.01,
            "max_single_lead_drop": 0.02,
            "max_high_flow_mae_relative_increase": 0.05,
        }
        self.budget_summary = budget_summary or {
            "max_agent_rounds": MAX_AGENT_ROUNDS,
            "max_optimization_cycles": MAX_OPTIMIZATION_CYCLES,
        }

    def freeze(
        self,
        *,
        task_id: str,
        source_scheme_id: str,
        gate_decision_id: str | None = None,
    ) -> str:
        task = self.repository.get_task(task_id)
        source = self.repository.get_scheme(source_scheme_id)
        if source.task_id != task_id:
            raise ValueError("cross-task references are forbidden")
        if source.status not in ("base", "accepted", "candidate", "frozen"):
            raise ValueError(f"scheme cannot be frozen: status={source.status}")
        config = copy.deepcopy(source.config_json or {})
        missing = []
        if not config.get("model_id") and not source.model_id:
            missing.append("model_id")
        if config.get("warmup_days") is None:
            missing.append("warmup_days")
        if not isinstance(config.get("parameters"), dict) or not config.get("parameters"):
            missing.append("parameters")
        if missing:
            raise ValueError(f"scheme cannot be frozen: missing {missing[0]}")
        freeze_contract = {
            "model_id": config.get("model_id") or source.model_id,
            "leads": [1, 2, 3],
            "forcing_mode": task.forcing_mode,
            "preprocessing_version": config.get("preprocessing_version", "v1"),
            "warmup_days": int(config["warmup_days"]),
            "gate_policy": dict(self.gate_policy),
            "budget_summary": dict(self.budget_summary),
        }
        config["freeze_contract"] = freeze_contract
        config["provenance"] = {
            "source_scheme_id": source_scheme_id,
            "gate_decision_id": gate_decision_id,
            "frozen_by": "FreezeService",
        }
        frozen_id = f"{task_id}--frozen-{source_scheme_id[-24:]}"
        if len(frozen_id) > 128:
            frozen_id = f"{task_id}--frozen-{sha256_bytes(source_scheme_id.encode())[:16]}"
        content_hash = sha256_bytes(canonical_json(config).encode("utf-8"))
        self.repository.create_scheme(
            scheme_id=frozen_id,
            task_id=task_id,
            model_id=source.model_id,
            status="frozen",
            config=config,
            content_hash=content_hash,
        )
        self.repository.ensure_task_state(task_id, current_scheme_id=source_scheme_id)
        self.repository.update_task_state(task_id, current_scheme_id=frozen_id)
        return frozen_id
