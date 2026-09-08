import numpy as np
import pytest

from hydro_agent.evaluation.metrics import bias, mae, nse


def test_metrics_match_hand_calculation():
    obs = np.array([1.0, 2.0, 3.0])
    sim = np.array([1.0, 2.0, 2.0])
    assert mae(obs, sim) == pytest.approx(1.0 / 3.0)
    assert bias(obs, sim) == pytest.approx(-1.0 / 6.0)
    expected_nse = 1.0 - 1.0 / 2.0
    assert nse(obs, sim) == pytest.approx(expected_nse)


def test_nse_rejects_single_observation():
    with pytest.raises(ValueError, match="at least two"):
        nse([1.0], [1.0])


@pytest.mark.parametrize("fn", [nse, mae, bias])
def test_metrics_reject_nan_and_shape_mismatch(fn):
    with pytest.raises(ValueError):
        fn([1.0, 2.0], [1.0])
    with pytest.raises(ValueError):
        fn([1.0, float("nan")], [1.0, 2.0])
