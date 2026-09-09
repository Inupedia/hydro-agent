"""End-to-end reliability smoke for the open-data Leaf River adapter."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from hydro_agent.data.adapters.open_basin import LEAF_RIVER, build_open_basin_case
from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.us_plans import UsModelPlanService, UsPlanRequest


def main() -> None:
    root = Path("artifacts/open-adapter-smoke")
    root.mkdir(parents=True, exist_ok=True)
    basin_root = root / "basins"
    plans_root = root / "plans"
    catalog = BasinCatalog(basin_root)

    # Need >= history_days(90)+3 continuous days for RealWorkbenchKernel snapshots.
    start = date(2019, 10, 1)
    end = date(2020, 3, 31)
    print("=== OPEN ADAPTER: Leaf River download ===", flush=True)

    def progress(stage: str, current: str, frac: float) -> None:
        print(f"[{frac:5.1%}] {stage}: {current}", flush=True)

    summary = build_open_basin_case(
        catalog.directory(LEAF_RIVER.basin_id),
        LEAF_RIVER,
        start=start,
        end=end,
        progress=progress,
    )
    print("SUMMARY", json.dumps(summary, indent=2), flush=True)

    # Reliability checks
    assert summary["boundary_check"]["accepted"], summary["boundary_check"]
    assert summary["n_forcing"] >= 150, summary
    assert summary["n_flow"] >= 150, summary
    assert 0.0 <= summary["precip_mean"] <= 80.0, summary["precip_mean"]
    assert 0.0 < summary["pet_mean"] <= 15.0, summary["pet_mean"]
    assert summary["q_mean"] > 0, summary["q_mean"]
    assert summary["dem_tiles"] >= 1, summary

    meta = catalog._refresh_catalog_status(LEAF_RIVER.basin_id)
    assert meta["ready_for_build"] and meta["materials"]["gis"] and meta["materials"]["dem"]

    print("=== BUILD lumped model plan ===", flush=True)
    plans = UsModelPlanService(plans_root, catalog)
    plan = plans.create(
        UsPlanRequest(
            basin_id=LEAF_RIVER.basin_id,
            model_mode="lumped",
            warmup_days=30,
        )
    )
    for _ in range(100):
        plan = plans.get(plan["plan_id"])
        if plan["status"] in ("awaiting_review", "failed", "ready"):
            break
        time.sleep(0.05)
    assert plan["status"] == "awaiting_review", plan.get("error")
    plan = plans.confirm(plan["plan_id"], plan["boundary_hash"])
    for _ in range(120):
        plan = plans.get(plan["plan_id"])
        if plan["status"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert plan["status"] == "ready", plan.get("error")
    assert (plans.directory(plan["plan_id"]) / "normalized" / "forcing.jsonl").is_file()
    print("PLAN READY", plan["plan_id"], plan.get("suggested_start"), plan.get("suggested_end"), flush=True)
    plans.pool.shutdown(wait=False)
    print("=== RELIABILITY SMOKE PASSED ===", flush=True)


if __name__ == "__main__":
    main()
