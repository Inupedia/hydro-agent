"""Lightweight calibration-case memory built from audited evidence.

V1 intentionally stores JSONL instead of training a domain model. The schema is
stable enough to support retrieval/few-shot prompting later without changing the
Agent/optimizer boundary.
"""

from __future__ import annotations

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
    # Defaults keep pre-dual-gate JSONL cases readable after the schema upgrade.
    adoption_status: str = "UNKNOWN"
    qualification_status: str = "NOT_EVALUATED"
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


def lesson_from_gate(
    status: str,
    *,
    adoption_status: str | None = None,
    qualification_status: str | None = None,
) -> str:
    """Summarize what may safely be learned from adoption and qualification evidence."""

    adoption = str(adoption_status or "").upper()
    qualification = str(qualification_status or "").upper()
    if adoption == "ADOPT" and qualification == "QUALIFIED":
        return "候选已被采用且通过独立资格评价，可作为经验证的正案例。"
    if adoption == "ADOPT" and qualification in {"UNQUALIFIED", "NOT_EVALUATED"}:
        return "候选相对基线有改进，可作为后续工作的基线，但尚未通过独立资格评价，不能标记为达标正案例。"
    if status == "ROLLBACK" or adoption == "ROLLBACK":
        if qualification == "QUALIFIED":
            return "候选绝对资格指标虽达标，但相对基线验证触发回滚条件；不得替换当前方案，也不标记为采用成功。"
        return "候选在独立验证中退化，应回滚并降低本轮假设优先级。"
    if status == "ACCEPT":
        # Legacy single-gate cases had no separate qualification field.
        return "独立验证支持候选，可将本轮假设与率定方案作为历史正案例。"
    return "候选未达到独立验证 Gate；保留基线并重新诊断，不把率定窗改善当作成功。"
