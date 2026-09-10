import json
from pathlib import Path

from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.plans import ModelPlanService, digest, write_json


def setup_plan(deps, tmp_path):
    service = ModelPlanService(tmp_path / 'plans', tmp_path / 'academy')
    deps.model_plans = service
    deps.basins = BasinCatalog(tmp_path / 'basins', academy=tmp_path / 'academy')
    deps.mode = 'real'
    plan_id = 'plan-123456abcdef'
    root = service.directory(plan_id)
    root.mkdir()
    scheme = json.loads((Path(__file__).parents[1]/'fixtures/xaj/scheme.json').read_text())
    scheme['routing'] = {'dp': 1, 'ke': 24, 'xe': 0.2}
    write_json(root / 'scheme.json', scheme)
    write_json(
        root / 'plan.json',
        dict(
            plan_id=plan_id,
            status='ready',
            boundary_reviewed=True,
            basin_id='yaogu',
            content_hash='v1',
            suggested_start='1991-01-01',
            data_end='2003-12-31',
            files={'scheme.json': digest(root / 'scheme.json')},
        ),
    )
    return service, plan_id


def payload(plan_id):
    return dict(
        basin_id='yaogu',
        model_id='xaj',
        start_date='1991-06-01',
        end_date='1991-06-03',
        forcing_mode='R',
        base_scheme_id='base',
        allow_optimization=True,
        model_plan_id=plan_id,
    )


def test_real_task_requires_plan_and_keeps_routing(client, app_dependencies, tmp_path):
    service, plan_id = setup_plan(app_dependencies, tmp_path)
    assert client.post('/api/tasks', json=payload(None)).status_code == 400
    created = client.post('/api/tasks', json=payload(plan_id))
    assert created.status_code == 201, created.text
    scheme = app_dependencies.repository.get_scheme(created.json()['current_scheme_id'])
    assert scheme.config_json['routing']['dp'] == 1
    assert scheme.config_json['model_plan_hash'] == 'v1'
    assert created.json()['model_plan_id'] == plan_id
    (service.directory(plan_id) / 'scheme.json').write_text('{}', encoding='utf-8')
    assert client.post(f"/api/tasks/{created.json()['task_id']}/run").status_code == 409
    service.pool.shutdown()


def test_wrong_basin_and_future_forcing_rejected(client, app_dependencies, tmp_path):
    service, plan_id = setup_plan(app_dependencies, tmp_path)
    for change in ({'basin_id': 'wrong'}, {'forcing_mode': 'F'}, {'start_date': '1988-01-01'}):
        response = client.post('/api/tasks', json={**payload(plan_id), **change})
        assert response.status_code == 400
    assert app_dependencies.repository.list_tasks() == []
    service.pool.shutdown()


def test_list_basins_endpoint(client, app_dependencies, tmp_path):
    from hydro_agent.modeling.plans import bundled_academy_root

    catalog = BasinCatalog(tmp_path / 'basins', academy=bundled_academy_root())
    app_dependencies.basins = catalog
    response = client.get('/api/basins')
    assert response.status_code == 200
    body = response.json()
    assert any(row['basin_id'] == 'yaogu' and row['ready_for_build'] for row in body)
    assert not any(row['basin_id'].startswith('camels_') or row['basin_id'].startswith('usgs_') for row in body)
