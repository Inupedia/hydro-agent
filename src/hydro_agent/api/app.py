from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from hydro_agent.api.deps import AppDependencies
from hydro_agent.api.executor import TaskExecutor
from hydro_agent.api.routes import basins, hydrologist, model_plans, results, runs, tasks


def _upgrade_product_services(deps: AppDependencies) -> None:
    """Replace the legacy model-plan implementation before routes/executor use it."""
    if deps.model_plans is None or deps.basins is None:
        return
    from hydro_agent.modeling.product_plans import ProductUsModelPlanService

    if isinstance(deps.model_plans, ProductUsModelPlanService):
        return
    old = deps.model_plans
    deps.model_plans = ProductUsModelPlanService(old.root, deps.basins)
    # The manual hydrologist endpoint is compatibility-only, but if it remains
    # reachable make it inspect the same plan service rather than a stale instance.
    if deps.hydrologist is not None:
        for attr in ("plans", "model_plans", "plan_service"):
            if hasattr(deps.hydrologist, attr):
                try:
                    setattr(deps.hydrologist, attr, deps.model_plans)
                except Exception:
                    pass


def create_app(deps: AppDependencies, *, static_dir: Path | None = None) -> FastAPI:
    _upgrade_product_services(deps)
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
        return {
            "status": "ok",
            "model_preparation": deps.model_plans is not None,
            "basin_catalog": getattr(deps, "basins", None) is not None,
            "hydrologist_tune": False,
            "automatic_calibration": True,
            "orchestrator": "langgraph",
            "mode": getattr(deps, "mode", "demo"),
            "provider_model": getattr(deps, "provider_model", None),
        }

    app.include_router(basins.router)
    app.include_router(basins.downloads_router)
    app.include_router(model_plans.router)
    # Compatibility API stays mounted for old records, but the product UI no longer
    # exposes manual tuning as a parallel workflow.
    app.include_router(hydrologist.router)
    app.include_router(tasks.router)
    app.include_router(runs.router)
    app.include_router(results.router)

    if static_dir is not None:
        root = Path(static_dir).resolve()
        assets = root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str = ""):
            if full_path.startswith("api/"):
                return {"detail": "Not Found"}
            candidate = (root / full_path).resolve()
            if full_path and candidate.is_file() and (
                candidate == root or root in candidate.parents
            ):
                return FileResponse(candidate)
            return FileResponse(root / "index.html")

    return app
