import pytest

from hydro_agent.experience.convergence import compute_convergence


def events(*event_types):
    return [{"event_type": event_type} for event_type in event_types]


def test_many_structural_events_remain_learning():
    summary = compute_convergence(
        events(
            "CREATE",
            "REINFORCE",
            "SPLIT",
            "MERGE",
            "KEEP",
            "SUPERSEDE",
        ),
        window=6,
    )

    assert summary.status == "learning"
    assert summary.structural_count == 4
    assert summary.reason == "recent_window_contains_frequent_structural_change"


def test_state_optimization_dominates_converging_window():
    summary = compute_convergence(
        events(
            "KEEP",
            "REINFORCE",
            "WEAKEN",
            "KEEP",
            "REINFORCE",
            "CREATE",
        ),
        window=6,
    )

    assert summary.status == "converging"
    assert summary.structural_count == 1
    assert summary.non_structural_count == 5


def test_two_quiet_windows_are_converged():
    quiet = ("KEEP", "REINFORCE", "WEAKEN", "KEEP")
    summary = compute_convergence(events(*(quiet + quiet)), window=4)

    assert summary.status == "converged"
    assert summary.reason == "two_consecutive_quiet_windows"


def test_structural_change_after_convergence_reopens_learning():
    quiet = ("KEEP", "REINFORCE", "WEAKEN")
    summary = compute_convergence(
        events(*(quiet + quiet + ("SPLIT",))),
        window=3,
    )

    assert summary.status == "reopened"
    assert summary.reason == "structural_change_after_two_quiet_windows"


def test_invalid_event_and_window_are_rejected():
    with pytest.raises(ValueError, match="window"):
        compute_convergence([], window=1)
    with pytest.raises(ValueError, match="event_type"):
        compute_convergence([{}], window=3)
