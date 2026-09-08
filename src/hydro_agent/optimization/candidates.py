from __future__ import annotations

import copy
import json

from hydro_agent.execution.hashing import sha256_bytes


def canonical_json(value) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


class CandidateSchemeService:
    def __init__(self, repository):
        self.repository = repository

    def register_candidate(
        self, *, base_scheme_id: str, action_run_id: str, calibration_payload: dict
    ) -> str:
        base = self.repository.get_scheme(base_scheme_id)
        parameters = calibration_payload.get("candidate_parameters")
        strategy_id = calibration_payload.get("strategy_id")
        if not isinstance(parameters, dict) or not strategy_id:
            raise ValueError("invalid calibration payload")
        config = copy.deepcopy(base.config_json)
        config["parameters"] = {str(k): float(v) for k, v in parameters.items()}
        config["provenance"] = {
            "base_scheme_id": base_scheme_id,
            "created_by_action_run_id": action_run_id,
            "strategy_id": strategy_id,
        }
        short_run = action_run_id.replace("run-", "")[-12:]
        # Keep scheme ids short: Identifier max length is 128.
        scheme_id = f"{base.task_id}--cand-{short_run}"
        content_hash = sha256_bytes(canonical_json(config).encode("utf-8"))
        self.repository.create_scheme(
            scheme_id=scheme_id,
            task_id=base.task_id,
            model_id=base.model_id,
            status="candidate",
            config=config,
            content_hash=content_hash,
        )
        return scheme_id
