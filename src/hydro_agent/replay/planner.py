from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from hydro_agent.data.policy import DataAccessViolation
from hydro_agent.replay.contracts import ReplayCase, ReplayPlan


class ReplayPlanner:
    def __init__(self, repository, *, resolver, issue_hour: int = 0):
        if not 0 <= issue_hour <= 23:
            raise ValueError("issue_hour must be 0..23")
        self.repository = repository
        self.resolver = resolver
        self.issue_hour = issue_hour

    def plan(self, task_id: str, start_date: date, end_date: date) -> ReplayPlan:
        if end_date < start_date:
            raise ValueError("end_date before start_date")
        task = self.repository.get_task(task_id)
        state = self.repository.ensure_task_state(task_id)
        scheme = self.repository.get_scheme(state.current_scheme_id)
        if scheme.status != "frozen":
            raise ValueError("current scheme must be frozen for replay planning")
        cases: list[ReplayCase] = []
        seen: set[datetime] = set()
        day = start_date
        while day <= end_date:
            issue = datetime(day.year, day.month, day.day, self.issue_hour, tzinfo=timezone.utc)
            if issue in seen:
                raise ValueError("duplicate issue times")
            seen.add(issue)
            issue_iso = issue.isoformat().replace("+00:00", "Z")
            try:
                snapshot_id = self.resolver.resolve(task_id, "forecast", issue_iso)
            except DataAccessViolation as exc:
                raise DataAccessViolation("no legal forcing") from exc
            cases.append(ReplayCase(issue_time=issue, data_snapshot_id=snapshot_id))
            day += timedelta(days=1)
        return ReplayPlan(
            task_id=task_id,
            scheme_id=scheme.scheme_id,
            forcing_mode=task.forcing_mode,
            cases=tuple(cases),
        )
