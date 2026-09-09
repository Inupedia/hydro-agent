
import pytest

from hydro_agent.modeling.plans import ModelPlanService, digest, write_json


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
