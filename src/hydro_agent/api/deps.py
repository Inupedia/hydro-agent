from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.persistence.repository import HydroRepository


@dataclass
class AppDependencies:
    repository: HydroRepository
    runtime_factory: Callable[[], AgentRuntime]
    report_root: str | None = None
    task_configs: dict[str, Any] = field(default_factory=dict)
    report_artifacts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metrics_by_task: dict[str, dict[str, float]] = field(default_factory=dict)
