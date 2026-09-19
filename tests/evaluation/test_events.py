from datetime import date, timedelta

from hydro_agent.evaluation.events import EventSegmentationConfig, segment_flood_events


def test_flow_only_segmentation_is_deterministic_and_marks_basis():
    start = date(2020, 7, 1)
    dates = [start + timedelta(days=i) for i in range(12)]
    observed = [10, 11, 12, 20, 50, 90, 45, 18, 12, 13, 14, 12]

    config = EventSegmentationConfig(
        high_flow_quantile=0.75,
        min_event_steps=3,
        min_separation_steps=2,
    )
    events = segment_flood_events(
        dates=dates,
        observed=observed,
        precipitation=None,
        config=config,
    )
    repeated = segment_flood_events(
        dates=dates,
        observed=observed,
        precipitation=None,
        config=config,
    )

    assert events == repeated
    assert len(events) == 1
    assert events[0].event_id == "event-001"
    assert events[0].basis == "flow_only"
    assert events[0].start <= dates[4]
    assert events[0].peak_time == dates[5]
    assert events[0].end >= dates[6]


def test_rainfall_assisted_segmentation_marks_rainfall_runoff_basis():
    start = date(2020, 7, 1)
    dates = [start + timedelta(days=i) for i in range(10)]
    observed = [8, 9, 10, 14, 28, 70, 32, 16, 11, 9]
    rain = [0, 0, 0, 12, 35, 8, 0, 0, 0, 0]

    events = segment_flood_events(
        dates=dates,
        observed=observed,
        precipitation=rain,
        config=EventSegmentationConfig(high_flow_quantile=0.75),
    )

    assert len(events) == 1
    assert events[0].basis == "rainfall_runoff"
    assert events[0].rain_start == dates[3]
    assert events[0].rain_end == dates[5]


def test_rainfall_without_runoff_peak_does_not_create_event():
    start = date(2020, 7, 1)
    dates = [start + timedelta(days=i) for i in range(8)]
    observed = [10.0] * 8
    rain = [0, 0, 30, 25, 0, 0, 0, 0]

    events = segment_flood_events(
        dates=dates,
        observed=observed,
        precipitation=rain,
        config=EventSegmentationConfig(high_flow_quantile=0.9),
    )

    assert events == ()
