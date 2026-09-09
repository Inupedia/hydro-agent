import json
from pathlib import Path

from hydro_agent.modeling.basins import BasinCatalog
from hydro_agent.modeling.plans import digest, write_json
from hydro_agent.modeling.us_plans import UsModelPlanService


def setup_plan(deps, tmp_path):
    catalog = BasinCatalog(tmp_path / 'basins')
    service = UsModelPlanService(tmp_path / 'plans', catalog)
    deps.model_plans = service
    deps.basins = catalog
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
            basin_id='camels_13235000',
            content_hash='v1',
            suggested_start='2020-04-01',
            data_end='2020-05-31',
            files={'scheme.json': digest(root / 'scheme.json')},
        ),
    )
    return service, plan_id


def payload(plan_id):
    return dict(
        basin_id='camels_13235000',
        model_id='xaj',
        start_date='2020-04-20',
        end_date='2020-04-22',
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
    for change in ({'basin_id': 'wrong'}, {'forcing_mode': 'F'}, {'start_date': '2019-01-01'}):
        response = client.post('/api/tasks', json={**payload(plan_id), **change})
        assert response.status_code == 400
    assert app_dependencies.repository.list_tasks() == []
    service.pool.shutdown()


def test_list_basins_endpoint(client, app_dependencies, tmp_path):
    catalog = BasinCatalog(tmp_path / 'basins')
    app_dependencies.basins = catalog
    from hydro_agent.modeling.downloads import BasinDownloadService

    app_dependencies.basin_downloads = BasinDownloadService(catalog)
    response = client.get('/api/basins')
    assert response.status_code == 200
    body = response.json()
    assert any(row['basin_id'] == 'camels_13235000' for row in body)
