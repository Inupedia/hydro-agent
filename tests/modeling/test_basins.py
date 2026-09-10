from datetime import date, timedelta

from hydro_agent.modeling.basins import BUILTIN_BASINS, BasinCatalog
from hydro_agent.modeling.us_plans import UsModelPlanService, UsPlanRequest


def _seed_hydro(catalog: BasinCatalog, basin_id: str = "camels_13235000", days: int = 100) -> None:
    hydro = catalog.hydro_dir(basin_id)
    hydro.mkdir(parents=True, exist_ok=True)
    start = date(2020, 4, 1)
    lines_f = []
    lines_q = []
    for i in range(days):
        day = start + timedelta(days=i)
        lines_f.append(
            '{"valid_date":"%s","precipitation_mm_day":1.0,"pet_mm_day":2.0,'
            '"source_kind":"reanalysis","source":"test","available_at":"%sT00:00:00+00:00"}'
            % (day.isoformat(), (day + timedelta(days=1)).isoformat())
        )
        lines_q.append(
            '{"valid_date":"%s","discharge_m3s":10.0,"source":"usgs","available_at":"%sT00:00:00+00:00"}'
            % (day.isoformat(), (day + timedelta(days=1)).isoformat())
        )
    (hydro / "forcing.jsonl").write_text("\n".join(lines_f) + "\n", encoding="utf-8")
    (hydro / "flow.jsonl").write_text("\n".join(lines_q) + "\n", encoding="utf-8")
    (hydro / "basin.json").write_text(
        '{"basin_id":"camels_13235000","area_km2":100.0,"latitude":44.0,"longitude":-115.0,"usgs_site":"13235000","day_timezone":"UTC"}',
        encoding="utf-8",
    )
    catalog._refresh_catalog_status(basin_id)


def test_catalog_lists_builtin_and_marks_ready(tmp_path):
    catalog = BasinCatalog(tmp_path / "basins")
    rows = catalog.list()
    ids = {r["basin_id"] for r in rows}
    assert {b["basin_id"] for b in BUILTIN_BASINS} <= ids
    lowman = next(r for r in rows if r["basin_id"] == "camels_13235000")
    assert lowman["ready_for_build"] is False
    _seed_hydro(catalog)
    lowman = catalog._refresh_catalog_status("camels_13235000")
    assert lowman["ready_for_build"] is True
    assert lowman["materials"]["hydro"] is True


def test_us_plan_lumped_build_to_ready(tmp_path):
    catalog = BasinCatalog(tmp_path / "basins")
    _seed_hydro(catalog)
    service = UsModelPlanService(tmp_path / "plans", catalog)
    plan = service.create(
        UsPlanRequest(basin_id="camels_13235000", model_mode="lumped", warmup_days=5)
    )
    # Wait for first stage thread
    import time

    for _ in range(50):
        plan = service.get(plan["plan_id"])
        if plan["status"] in ("awaiting_review", "failed", "ready"):
            break
        time.sleep(0.05)
    assert plan["status"] == "awaiting_review", plan.get("error")
    plan = service.confirm(plan["plan_id"], plan["boundary_hash"])
    for _ in range(80):
        plan = service.get(plan["plan_id"])
        if plan["status"] in ("ready", "failed"):
            break
        time.sleep(0.05)
    assert plan["status"] == "ready", plan.get("error")
    assert (service.directory(plan["plan_id"]) / "normalized" / "forcing.jsonl").is_file()
    assert plan["basin_id"] == "camels_13235000"
    service.pool.shutdown(wait=False)


def test_download_job_progress_record(tmp_path, monkeypatch):
    from hydro_agent.modeling.downloads import BasinDownloadService

    catalog = BasinCatalog(tmp_path / "basins")
    service = BasinDownloadService(catalog)

    def fake_run(job_id):
        service._update(job_id, status="running", stage="multimet", current_file="zmetadata.json", fraction=0.2)
        service._update(job_id, status="succeeded", stage="done", fraction=1.0, current_file=None)
        catalog.hydro_dir("camels_01123000").mkdir(parents=True, exist_ok=True)
        (catalog.hydro_dir("camels_01123000") / "forcing.jsonl").write_text("{}\n", encoding="utf-8")
        (catalog.hydro_dir("camels_01123000") / "flow.jsonl").write_text("{}\n", encoding="utf-8")
        catalog._refresh_catalog_status("camels_01123000")

    monkeypatch.setattr(service, "_run", fake_run)
    job = service.start("camels_01123000", components=["hydro"])
    assert job["job_id"].startswith("dl-")
    import time

    for _ in range(40):
        done = service.get_job(job["job_id"])
        if done["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.05)
    assert done["status"] == "succeeded"
    assert done["fraction"] == 1.0
    service.pool.shutdown(wait=False)
