#!/usr/bin/env python3
"""Smoke-run the workbench API until phase E completes (or fail loudly)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def req(method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        text = exc.read().decode()
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"raw": text}
        return exc.code, payload


def main() -> int:
    code, health = req("GET", "/api/health")
    print("HEALTH", code, health)
    if code >= 400 or health.get("status") != "ok":
        return 1
    payload = {
        "basin_id": "camels_13235000",
        "model_id": "xaj",
        "start_date": "2020-04-29",
        "end_date": "2020-05-01",
        "forcing_mode": "R",
        "base_scheme_id": "scheme-base",
        "allow_optimization": True,
        "max_agent_decision_rounds": 20,
        "max_optimization_cycles": 4,
    }
    code, task = req("POST", "/api/tasks", payload)
    print("CREATE", code, task.get("task_id"))
    if code >= 400:
        print(task)
        return 1
    task_id = task["task_id"]
    code, run = req("POST", f"/api/tasks/{task_id}/run")
    print("START", code, run.get("status"), run.get("worker_active"))
    deadline = time.time() + 60 * 35
    last = None
    while time.time() < deadline:
        _, run = req("GET", f"/api/tasks/{task_id}/run")
        _, timeline = req("GET", f"/api/tasks/{task_id}/timeline")
        actions = [(t.get("action"), t.get("status")) for t in timeline]
        summary = {
            "status": run.get("status"),
            "phase": run.get("phase"),
            "active": run.get("worker_active"),
            "follow": run.get("needs_follow_up"),
            "err": run.get("llm_error"),
            "actions": actions,
            "dec": run.get("llm_decision_action"),
        }
        line = json.dumps(summary, ensure_ascii=False)
        if line != last:
            print(time.strftime("%H:%M:%S"), line)
            last = line
        if run.get("llm_error"):
            print("FAILED", run.get("llm_error"))
            return 2
        if (not run.get("worker_active")) and (
            run.get("status") == "completed"
            or (run.get("phase") == "E" and not run.get("needs_follow_up"))
        ):
            _, results = req("GET", f"/api/tasks/{task_id}/results")
            _, agent_log = req("GET", f"/api/tasks/{task_id}/agent-log")
            print("COMPLETED", task_id)
            print("ACTIONS", actions)
            print("GATE", results.get("gate"))
            print("METRICS", results.get("metrics"))
            print("ROUNDS", len(agent_log.get("rounds") or []))
            return 0
        time.sleep(3)
    print("TIMEOUT", task_id)
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
