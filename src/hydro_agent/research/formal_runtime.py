"""Formal-only rolling evaluation adapters for preregistered research runs."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from hydro_agent.agent.contracts import ActionCode, AgentDecision, EvidencePacket
from hydro_agent.agent.tools import information_hash
from hydro_agent.workbench.rolling_sampling import (
    FORECAST_LEAD_DAYS,
    evenly_spaced_issue_days,
)
from hydro_agent.workbench.validation_gate import RealValidationGate, ValidationWindow


def _day(value: object) -> date:
    return date.fromisoformat(str(value)[:10])


class PreregisteredValidationGate(RealValidationGate):
    """Development Gate that evaluates only preregistered full-lead-safe issues."""

    def issue_days_for(self, task_id: str, window: ValidationWindow) -> tuple[date, ...]:
        cfg = self.task_configs.get(task_id) or {}
        raw_limit = cfg.get("development_rolling_issue_limit")
        if raw_limit is None:
            raise ValueError("formal development Gate requires development_rolling_issue_limit")
        days = evenly_spaced_issue_days(window.start, window.end, int(raw_limit))
        if len(days) < 2:
            raise ValueError("formal development Gate requires at least two safe issue days")
        return days

    def ensure_forecasts(self, task_id: str, scheme_id: str, window: ValidationWindow) -> None:
        for day in self.issue_days_for(task_id, window):
            issue = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            self.forecast.forecast(
                task_id=task_id,
                scheme_id=scheme_id,
                issue_time=issue.isoformat().replace("+00:00", "Z"),
                policy=self.policy,
            )


class PreregisteredReplayHandler:
    """A11 replay over sampled issues while A12 retains the full final window."""

    def __init__(self, kernel, task_configs: dict):
        self.kernel = kernel
        self.task_configs = task_configs

    def execute(self, task_id: str, decision: AgentDecision) -> EvidencePacket:
        cfg = self.task_configs.get(task_id) or {}
        raw_start = cfg.get("final_test_start_date")
        raw_end = cfg.get("final_test_end_date")
        raw_limit = cfg.get("final_test_rolling_issue_limit")
        if raw_start is None or raw_end is None or raw_limit is None:
            raise ValueError("formal replay requires final-test dates and rolling issue limit")

        start = _day(raw_start)
        end = _day(raw_end)
        issue_days = evenly_spaced_issue_days(start, end, int(raw_limit))
        if len(issue_days) < 2:
            raise ValueError("formal replay requires at least two safe issue days")

        plan = self.kernel.planner.plan_issues(task_id, issue_days)
        forecasts = self.kernel.replay_service.execute(plan)
        task = self.kernel.repository.get_task(task_id)
        if task.phase == "F":
            self.kernel.repository.set_task_phase(task_id, "E")

        observations = (
            f"forecast_count={len(forecasts)}",
            f"scheme_id={plan.scheme_id}",
            f"final_test_window={start.isoformat()}..{end.isoformat()}",
            "rolling_sampling=evenly_spaced_full_lead_safe",
            f"rolling_issue_count={len(issue_days)}",
            f"rolling_issue_first={issue_days[0].isoformat()}",
            f"rolling_issue_last={issue_days[-1].isoformat()}",
            f"rolling_max_lead_days={FORECAST_LEAD_DAYS}",
            "continuous_final_test_window_preserved=true",
        )
        metrics = {
            "forecast_count": float(len(forecasts)),
            "rolling_issue_count": float(len(issue_days)),
        }
        return EvidencePacket(
            evidence_id=f"ev-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            action=ActionCode.A11_REPLAY,
            status="succeeded",
            observations=observations,
            metrics=metrics,
            artifact_ids=tuple(forecast.forecast_id for forecast in forecasts),
            new_information_hash=information_hash(
                action=ActionCode.A11_REPLAY,
                status="succeeded",
                observations=observations,
                metrics=metrics,
            ),
        )


def build_formal_tools(kernel, *, task_configs: dict):
    """Install formal sampling without changing the default product/smoke stack."""

    kernel.validation_gate = PreregisteredValidationGate(
        repository=kernel.repository,
        forecast_service=kernel.forecast,
        source=kernel.source,
        policy=kernel.validation_gate.policy,
        task_configs=task_configs,
    )
    tools = kernel.build_tools(task_configs=task_configs)
    tools.register(
        ActionCode.A11_REPLAY,
        PreregisteredReplayHandler(kernel, task_configs),
    )
    return tools
