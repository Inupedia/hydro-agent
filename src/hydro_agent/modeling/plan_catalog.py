"""Dispatch model-plan operations to the builder for each basin family."""

from __future__ import annotations

import json
import re
from pathlib import Path

from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.plans import BUNDLED_BASIN_ID, ModelPlanService, PlanRequest
from hydro_agent.modeling.us_plans import UsModelPlanService, UsPlanRequest


class BasinModelPlanService:
    """Expose Yaogu and downloaded USGS builders through one API service."""

    def __init__(self, root: Path, academy: Path, catalog: BasinCatalog):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.yaogu = ModelPlanService(self.root, academy)
        self.usgs = UsModelPlanService(self.root, catalog)

    def _plan(self, plan_id: str) -> dict:
        if not re.fullmatch(r"plan-[a-f0-9]{12}", plan_id):
            raise ValueError("invalid model plan id")
        path = self.root / plan_id / "plan.json"
        if not path.is_file():
            raise KeyError(plan_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _for_plan(self, plan_id: str):
        plan = self._plan(plan_id)
        return self.yaogu if plan.get("basin_id") == BUNDLED_BASIN_ID else self.usgs

    def list(self) -> list[dict]:
        plans = [self._plan(path.parent.name) for path in self.root.glob("plan-*/plan.json")]
        return sorted(plans, key=lambda plan: plan["plan_id"], reverse=True)

    def create(self, request: PlanRequest) -> dict:
        if request.basin_id == BUNDLED_BASIN_ID:
            return self.yaogu.create(request)
        return self.usgs.create(UsPlanRequest.model_validate(request.model_dump()))

    def get(self, plan_id: str) -> dict:
        return self._for_plan(plan_id).get(plan_id)

    def delete(self, plan_id: str) -> None:
        self._for_plan(plan_id).delete(plan_id)

    def confirm(self, plan_id: str, boundary_hash: str) -> dict:
        return self._for_plan(plan_id).confirm(plan_id, boundary_hash)

    def require_ready(self, plan_id: str) -> dict:
        return self._for_plan(plan_id).require_ready(plan_id)

    def directory(self, plan_id: str) -> Path:
        if not re.fullmatch(r"plan-[a-f0-9]{12}", plan_id):
            raise ValueError("invalid model plan id")
        return self.root / plan_id
