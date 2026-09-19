from __future__ import annotations

from typing import Literal

from hydro_agent.execution.contracts import FrozenModel


class StandardEvaluationResult(FrozenModel):
    profile_id: str
    standard_id: str
    status: Literal["evaluated", "not_evaluated", "not_applicable"]
    grade: str | None = None
    summary: str | None = None


def not_evaluated_standard(*, profile_id: str, standard_id: str) -> StandardEvaluationResult:
    return StandardEvaluationResult(
        profile_id=profile_id,
        standard_id=standard_id,
        status="not_evaluated",
    )
