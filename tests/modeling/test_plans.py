
import pytest

from hydro_agent.modeling.plans import ModelPlanService, dem_runtime_error, digest, write_json


@pytest.fixture
def plans(tmp_path):
    service = ModelPlanService(tmp_path/'plans', tmp_path/'missing-academy')
    yield service
    service.pool.shutdown(wait=True)


def ready_plan(plans, config):
    plan_id = 'plan-123456abcdef'
    root = plans.directory(plan_id)
    root.mkdir()
    write_json(root/'scheme.json', config)
    payload = dict(plan_id=plan_id, status='ready', boundary_reviewed=True, basin_id='yaogu',
                   content_hash='immutable-v1', suggested_start='1990-01-01', data_end='2003-12-31',
                   files={'scheme.json':digest(root/'scheme.json')})
    write_json(root/'plan.json', payload)
    return payload


def test_ready_plan_rejects_changed_or_missing_inputs(plans):
    p = ready_plan(plans, {'parameters':{}})
    assert plans.require_ready(p['plan_id'])['status'] == 'ready'
    (plans.directory(p['plan_id'])/'scheme.json').write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='已变化'):
        plans.require_ready(p['plan_id'])


def test_review_is_bound_to_exact_map_version(plans):
    p = ready_plan(plans, {})
    plans._update(p['plan_id'], status='awaiting_review', boundary_hash='current', review_files=p['files'])
    with pytest.raises(ValueError, match='边界版本'):
        plans.confirm(p['plan_id'], 'stale')
    assert plans.get(p['plan_id'])['status'] == 'awaiting_review'


def test_incomplete_plan_cannot_be_used(plans):
    p = ready_plan(plans, {})
    plans._update(p['plan_id'], status='awaiting_review')
    with pytest.raises(ValueError, match='尚未完成'):
        plans.require_ready(p['plan_id'])


def test_restart_marks_interrupted_build_failed(tmp_path):
    root = tmp_path/'plans'
    write_json(root/'plan-123456abcdef/plan.json', {'status':'running'})
    service = ModelPlanService(root, tmp_path)
    assert service.get('plan-123456abcdef')['status'] == 'failed'
    service.pool.shutdown()


def test_paths_cannot_escape_plan_store(plans):
    with pytest.raises(ValueError):
        plans.directory('../../secrets')


def test_delete_removes_plan_but_blocks_in_flight_builds(plans):
    p = ready_plan(plans, {})
    plans.delete(p['plan_id'])
    with pytest.raises(KeyError):
        plans.get(p['plan_id'])
    running = ready_plan(plans, {})
    plans._update(running['plan_id'], status='running')
    with pytest.raises(ValueError, match='建模进行中'):
        plans.delete(running['plan_id'])


def test_create_rejects_other_basins(plans):
    from hydro_agent.modeling.plans import PlanRequest

    with pytest.raises(ValueError, match='仅支持'):
        plans.create(PlanRequest(basin_id='usgs_02472000'))


def test_bundled_academy_materials_exist():
    from hydro_agent.modeling.plans import academy_materials_ready, bundled_academy_root

    root = bundled_academy_root()
    assert academy_materials_ready(root)
    assert (root / 'examples/dem/yaogu/N22E111.hgt').is_file()
    assert (root / 'examples/dem/yaogu/N22E111.hgt.gz').is_file()
    assert (root / 'examples/data/ST_STNM.xlsx').is_file()


def test_dem_runtime_error_mentions_extra_when_rasterio_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'rasterio':
            raise ImportError('No module named rasterio')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    err = dem_runtime_error()
    assert err is not None
    assert 'rasterio' in err
    assert 'xaj-dem' in err


def test_normalize_writes_strict_xaj_basin(plans):
    import csv
    import json
    from datetime import date, timedelta

    from hydro_agent.models.xaj.contracts import XajBasin

    plan_id = 'plan-123456abcdef'
    root = plans.directory(plan_id)
    case = root / 'case'
    (case / 'gis').mkdir(parents=True)
    (case / 'parameters').mkdir()
    (case / 'model_inputs').mkdir()
    write_json(
        root / 'plan.json',
        dict(
            plan_id=plan_id,
            status='queued',
            config={'warmup_days': 5, 'model_mode': 'lumped'},
            model_mode='lumped',
        ),
    )
    with (case / 'gis' / 'units.csv').open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=['unit_id', 'area_km2'])
        writer.writeheader()
        writer.writerow({'unit_id': '1', 'area_km2': '100'})
    params = dict(
        kc='0.9', b='0.3', imp='0.02', wum='20', wlm='70', c='0.15', sm='25', ex='1.2',
        ki='0.4', kg='0.3', cs='0.65', lag='1', ci='0.85', cg='0.98', wm='150',
        dp='1', ke='24', xe='0.2',
    )
    with (case / 'parameters' / 'parameters.csv').open('w', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=list(params))
        writer.writeheader()
        writer.writerow(params)
    start = date(1991, 1, 1)
    for name, extra in (
        ('precipitation_mm', {'unit_1': '1'}),
        ('evaporation_mm', {'unit_1': '2'}),
        ('observed', {'discharge': '3'}),
    ):
        with (case / 'model_inputs' / f'{name}.csv').open('w', encoding='utf-8', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=['time', *extra])
            writer.writeheader()
            # 65 history days + 13 pre-validation diagnostic days + 3 leads.
            for i in range(100):
                writer.writerow({'time': str(start + timedelta(days=i)), **extra})
    plans._normalize(plan_id)
    basin = json.loads((root / 'normalized' / 'basin.json').read_text(encoding='utf-8'))
    XajBasin(**basin)
    meta = json.loads((root / 'normalized' / 'basin_meta.json').read_text(encoding='utf-8'))
    assert meta['model_plan_id'] == plan_id
    assert meta['unit_count'] == 1
    assert meta['model_mode'] == 'lumped'
    plan = json.loads((root / 'plan.json').read_text(encoding='utf-8'))
    assert plan['suggested_end'] > plan['suggested_start']


def test_write_json_survives_concurrent_replace(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor, as_completed

    path = tmp_path / 'catalog.json'

    def write_one(i: int) -> None:
        write_json(path, {'i': i})

    with ThreadPoolExecutor(max_workers=16) as pool:
        futs = [pool.submit(write_one, i) for i in range(40)]
        for fut in as_completed(futs):
            fut.result()
    payload = json.loads(path.read_text(encoding='utf-8'))
    assert 'i' in payload
    leftovers = list(tmp_path.glob('.catalog.json.*.tmp'))
    assert leftovers == []



def test_model_plan_persists_spatial_profile_and_unit_candidates_before_review(plans):
    import csv
    import json

    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    plan_id = "plan-abcdef123456"
    root = plans.directory(plan_id)
    gis = root / "case" / "gis"
    gis.mkdir(parents=True)
    write_json(
        root / "plan.json",
        {
            "plan_id": plan_id,
            "basin_id": "yaogu",
            "status": "running",
            "config": {"unit_count": 4},
            "stages": [],
        },
    )

    transform = from_origin(0.0, 4000.0, 1000.0, 1000.0)
    dem = np.asarray(
        [
            [100.0, 150.0, 300.0, 500.0],
            [120.0, 180.0, 350.0, 550.0],
            [140.0, 220.0, 420.0, 700.0],
            [160.0, 260.0, 480.0, 900.0],
        ],
        dtype="float32",
    )
    catchment = np.ones((4, 4), dtype="uint8")
    for name, data, dtype, nodata in (
        ("dem_projected.tif", dem, "float32", None),
        ("catchment.tif", catchment, "uint8", 0),
    ):
        with rasterio.open(
            gis / name,
            "w",
            driver="GTiff",
            width=4,
            height=4,
            count=1,
            dtype=dtype,
            crs="EPSG:3857",
            transform=transform,
            nodata=nodata,
        ) as dst:
            dst.write(data, 1)

    with (gis / "units.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["unit_id", "area_km2", "mean_elevation_m"],
        )
        writer.writeheader()
        writer.writerows(
            [
                {"unit_id": 1, "area_km2": 5.0, "mean_elevation_m": 160.0},
                {"unit_id": 2, "area_km2": 5.0, "mean_elevation_m": 360.0},
                {"unit_id": 3, "area_km2": 6.0, "mean_elevation_m": 620.0},
            ]
        )
    write_json(
        gis / "unit_topology.json",
        [
            {"unit_id": 1, "downstream_unit_id": 3},
            {"unit_id": 2, "downstream_unit_id": 3},
            {"unit_id": 3, "downstream_unit_id": 0},
        ],
    )
    write_json(
        gis / "streams.geojson",
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[111.0, 22.0], [111.05, 22.05], [111.1, 22.1]],
                    },
                }
            ],
        },
    )

    result = plans._persist_spatial_evidence(plan_id, max_units=8)

    assert (root / "spatial-profile.json").is_file()
    assert (root / "unit-candidates.json").is_file()
    assert (root / "unit-candidate-layers.json").is_file()
    saved = plans.get(plan_id)
    assert saved["unit_candidates"]
    assert saved["spatial_profile_status"] == "partial"
    assert saved["spatial_profile"]["elevation"]["status"] == "available"
    assert saved["spatial_profile"]["precipitation"]["status"] == "unknown"
    assert saved["spatial_profile"]["land_cover"]["status"] == "unknown"
    assert saved["spatial_profile"]["soil"]["status"] == "unknown"
    assert result["spatial_profile_status"] == "partial"
    artifact = json.loads((root / "unit-candidates.json").read_text(encoding="utf-8"))
    assert artifact["items"] == saved["unit_candidates"]


def test_spatial_evidence_artifacts_do_not_enter_boundary_review_hash(plans):
    plan_id = "plan-fedcba654321"
    root = plans.directory(plan_id)
    root.mkdir()
    write_json(
        root / "plan.json",
        {
            "plan_id": plan_id,
            "basin_id": "yaogu",
            "status": "running",
            "config": {},
            "stages": [],
        },
    )
    (root / "spatial-profile.json").write_text("{}\n", encoding="utf-8")
    (root / "unit-candidates.json").write_text('{"items": []}\n', encoding="utf-8")

    review = plans._boundary_review_manifest(plan_id)

    assert "spatial-profile.json" not in review
    assert "unit-candidates.json" not in review
