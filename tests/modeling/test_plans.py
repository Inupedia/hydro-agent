
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
            for i in range(80):
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
