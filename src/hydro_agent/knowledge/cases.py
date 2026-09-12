"""Lightweight calibration-case memory built from audited evidence.

V1 intentionally stores JSONL instead of training a domain model. The schema is
stable enough to support retrieval/few-shot prompting later without changing the
Agent/optimizer boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field

from hydro_agent.execution.contracts import FrozenModel


class CalibrationCase(FrozenModel):
    case_id: str = Field(min_length=1)
    basin_id: str = Field(min_length=1)
    hypothesis: str = Field(min_length=1)
    phenomenon: str = ""
    strategy_id: str = Field(min_length=1)
    optimizer: str = Field(min_length=1)
    param_groups: tuple[str, ...] = ()
    objective: str = "nse"
    calibration_metrics: dict[str, float] = Field(default_factory=dict)
    validation_metrics: dict[str, float] = Field(default_factory=dict)
    gate_status: str = Field(min_length=1)
    parameter_delta: dict[str, float] = Field(default_factory=dict)
    lesson: str = Field(min_length=1)


class CalibrationCaseMemory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, case: CalibrationCase) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(case.model_dump_json() + "\n")

    def list(self) -> tuple[CalibrationCase, ...]:
        if not self.path.is_file():
            return ()
        rows: list[CalibrationCase] = []
        with self.path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    rows.append(CalibrationCase.model_validate_json(line))
        return tuple(rows)

    def similar(
        self,
        *,
        hypothesis: str | None = None,
        param_groups: tuple[str, ...] | None = None,
        limit: int = 5,
    ) -> tuple[CalibrationCase, ...]:
        rows = list(self.list())
        if hypothesis:
            rows = [row for row in rows if row.hypothesis == hypothesis]
        if param_groups:
            wanted = set(param_groups)
            rows = [row for row in rows if wanted.intersection(row.param_groups)]
        return tuple(rows[-max(1, int(limit)) :])


def lesson_from_gate(status: str) -> str:
    if status == "ACCEPT":
        return "独立验证支持候选，可将本轮假设与率定方案作为正案例。"
    if status == "ROLLBACK":
        return "候选在独立验证中退化，应回滚并降低本轮假设优先级。"
    return "候选未达到独立验证 Gate；保留基线并重新诊断，不把率定窗改善当作成功。"
