from datetime import date, datetime, timezone
from types import SimpleNamespace

from hydro_agent.evaluation.metrics import build_evaluation_bundle
from hydro_agent.workbench.validation_gate import ValidationWindow, collect_aligned_lead_series


def _forecast(forecast_id: str, scheme_id: str, issue: date, values: dict[int, float]):
    return SimpleNamespace(
        forecast_id=forecast_id,
        scheme_id=scheme_id,
        issue_time=datetime(issue.year, issue.month, issue.day, tzinfo=timezone.utc),
        lead_values_json={str(key): float(value) for key, value in values.items()},
    )


def _gate_inputs(final_test_value: float):
    window = ValidationWindow(start=date(2000, 5, 5), end=date(2000, 5, 7))
    forecasts = []
    for number, issue in enumerate((date(2000, 5, 5), date(2000, 5, 6), date(2000, 5, 7))):
        forecasts.extend(
            (
                _forecast(
                    f"base-{number}",
                    "base",
                    issue,
                    {1: 10 + number, 2: 11 + number, 3: 12 + number},
                ),
                _forecast(
                    f"candidate-{number}",
                    "candidate",
                    issue,
                    {1: 9 + number, 2: 10 + number, 3: 11 + number},
                ),
            )
        )
    truth = {
        date(2000, 5, 5): 8.0,
        date(2000, 5, 6): 10.0,
        date(2000, 5, 7): 12.0,
        # First final-test observation. Changing this must have zero effect on Gate.
        date(2000, 5, 8): final_test_value,
        date(2000, 5, 9): 15.0,
        date(2000, 5, 10): 16.0,
    }
    base, candidate = collect_aligned_lead_series(
        forecasts=forecasts,
        base_scheme_id="base",
        candidate_scheme_id="candidate",
        truth=truth,
        window=window,
    )
    return base, candidate


def test_perturbing_final_test_truth_cannot_change_development_gate_inputs():
    normal = _gate_inputs(13.0)
    poisoned = _gate_inputs(999.0)
    assert normal == poisoned

    base, candidate = normal
    # In a 3-day compressed development window only lead-1 has two legal target
    # samples. lead-2/3 are explicitly unavailable instead of leaking final_test.
    assert len(base[1][0]) == 2
    assert len(base[2][0]) == 1
    assert len(base[3][0]) == 0

    base_bundle = build_evaluation_bundle("base", base)
    candidate_bundle = build_evaluation_bundle("candidate", candidate)
    assert [item.lead for item in base_bundle.leads] == [1]
    assert [item.lead for item in candidate_bundle.leads] == [1]
    assert base_bundle.primary_score == build_evaluation_bundle("base", poisoned[0]).primary_score
    assert candidate_bundle.primary_score == build_evaluation_bundle(
        "candidate", poisoned[1]
    ).primary_score
