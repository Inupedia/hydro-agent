from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from hydro_agent.agent.runtime import AgentRuntime
from hydro_agent.persistence.repository import HydroRepository


@dataclass
class LlmTrace:
    streaming: bool = False
    text: str = ""
    round_number: int = 0
    error: str | None = None
    decision_action: str | None = None


@dataclass
class AppDependencies:
    repository: HydroRepository
    runtime_factory: Callable[[], AgentRuntime]
    report_root: str | None = None
    task_configs: dict[str, Any] = field(default_factory=dict)
    report_artifacts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    metrics_by_task: dict[str, dict[str, float]] = field(default_factory=dict)
    mode: str = "demo"
    base_scheme_config: Callable[[], dict[str, Any]] | None = None
    provider_model: str | None = None
    llm_traces: dict[str, LlmTrace] = field(default_factory=dict)
    agent_round_logs: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _llm_lock: threading.Lock = field(default_factory=threading.Lock)

    def begin_llm_trace(self, task_id: str, *, round_number: int = 0) -> None:
        with self._llm_lock:
            self.llm_traces[task_id] = LlmTrace(
                streaming=True, text="", round_number=round_number, error=None
            )

    def append_llm_trace(self, task_id: str, token: str) -> None:
        with self._llm_lock:
            trace = self.llm_traces.setdefault(task_id, LlmTrace(streaming=True))
            trace.streaming = True
            trace.text += token
            # Keep UI buffer bounded.
            if len(trace.text) > 12000:
                trace.text = trace.text[-12000:]

    def finish_llm_trace(
        self, task_id: str, *, action: str | None = None, error: str | None = None
    ) -> None:
        with self._llm_lock:
            trace = self.llm_traces.setdefault(task_id, LlmTrace())
            trace.streaming = False
            if action:
                trace.decision_action = action
            if error:
                trace.error = error

    def get_llm_trace(self, task_id: str) -> LlmTrace:
        with self._llm_lock:
            return self.llm_traces.get(task_id) or LlmTrace()

    def append_agent_round_log(self, task_id: str, entry: dict[str, Any]) -> None:
        payload = dict(entry)
        payload.setdefault("occurred_at", datetime.now(timezone.utc).isoformat())
        with self._llm_lock:
            self.agent_round_logs.setdefault(task_id, []).append(payload)
            rows = list(self.agent_round_logs[task_id])
        self._rewrite_agent_log_file(task_id, rows)

    def update_last_agent_round_log(self, task_id: str, **fields: Any) -> None:
        with self._llm_lock:
            rows = self.agent_round_logs.setdefault(task_id, [])
            if not rows:
                return
            rows[-1] = {**rows[-1], **fields}
            snapshot = list(rows)
        self._rewrite_agent_log_file(task_id, snapshot)

    def _rewrite_agent_log_file(self, task_id: str, rows: list[dict[str, Any]]) -> None:
        root = self.report_root
        if not root:
            return
        path = Path(root) / task_id / "agent-log.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )

    def list_agent_round_logs(self, task_id: str) -> list[dict[str, Any]]:
        with self._llm_lock:
            memory = list(self.agent_round_logs.get(task_id) or [])
        if memory:
            return memory
        root = self.report_root
        if not root:
            return []
        path = Path(root) / task_id / "agent-log.jsonl"
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows
