from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.executor import TaskExecutor
from hydro_agent.api.routes import results, runs, tasks


def create_app(deps: AppDependencies) -> FastAPI:
    app = FastAPI(title="Hydro-Agent Workbench", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    executor = TaskExecutor(deps)
    deps.executor = executor  # type: ignore[attr-defined]
    app.state.deps = deps
    app.state.executor = executor

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(tasks.router)
    app.include_router(runs.router)
    app.include_router(results.router)
    return app
