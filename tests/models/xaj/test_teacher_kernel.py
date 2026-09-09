import hashlib
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from hydro_agent.models.xaj.contracts import XajBasin, XajScheme
from hydro_agent.models.xaj.upstream import MODEL_SHA256, simulate
from hydro_agent.models.xaj.vendor import xaj


@pytest.fixture
def scheme():
    path = Path(__file__).resolve().parents[2] / 'fixtures/xaj/scheme.json'
    return XajScheme.model_validate_json(path.read_text(encoding='utf-8'))


def forcing():
    rng = np.random.default_rng(42)
    values = np.zeros((103, 1, 2))
    values[:, 0, 0] = rng.uniform(0, 30, 103)
    values[:, 0, 1] = 2
    return values


def test_preheat_is_only_output_trimming(scheme):
    basin = XajBasin(basin_id='test', area_km2=100)
    all_values = simulate(scheme.model_copy(update={'warmup_days': 1}), basin, forcing())
    tail = simulate(scheme.model_copy(update={'warmup_days': 100}), basin, forcing())
    np.testing.assert_array_equal(all_values[-3:], tail)


def test_source_is_pinned():
    assert hashlib.sha256(Path(xaj.__file__).read_bytes()).hexdigest() == MODEL_SHA256


def test_adapter_matches_native_step_and_chunked_state(scheme, tmp_path):
    basin = XajBasin(basin_id='test', area_km2=137)
    raw = dict(rivid=1, area=137, dp=1, kc=.75, b=.25, c=.16, imp=.06,
               wm=120, wum=20, wlm=60, sm=20, ex=1.2, kg=.4, ki=.3,
               cg=.98, ci=.8, cs=.9, lag=2, ke=24, xe=.2)
    native = xaj.Model([xaj.make_parameter(raw, 86400)], 86400,
                       start_time=datetime(2000, 1, 1))
    rows = forcing()
    expected = []
    for row in rows[:70]:
        expected.append(float(native.step([row[0, 0]], [row[0, 1]]).sum_qsig))
    checkpoint = tmp_path / "restart.nc"
    xaj.write_restart(checkpoint, native)
    resumed = xaj.read_restart(checkpoint, native.params, 86400, native.time)
    for row in rows[70:]:
        expected.append(float(resumed.step([row[0, 0]], [row[0, 1]]).sum_qsig))
    adapted = XajScheme(**{**scheme.model_dump(), 'routing': {'dp': 1}})
    np.testing.assert_array_equal(simulate(adapted, basin, rows), expected[scheme.warmup_days:])


def test_unstable_routing_rejected(scheme):
    with pytest.raises(ValueError, match='Muskingum'):
        XajScheme(**{**scheme.model_dump(), 'routing': {'dp': 1, 'ke': 1}})
