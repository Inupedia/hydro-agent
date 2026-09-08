from datetime import datetime, timezone

from hydro_agent.data.lowman import normalize_caravan_row


def test_caravan_v16_uses_fao_pm_pet():
    published = datetime(2024, 1, 1, tzinfo=timezone.utc)
    row = normalize_caravan_row(
        {
            "date": "2020-01-01",
            "total_precipitation_sum": "5.0",
            "potential_evaporation_sum_FAO_PENMAN_MONTEITH": "2.5",
            "streamflow": "3.2",
        },
        area_km2=1184.0,
        available_at=published,
        streamflow_unit="m3/s",
    )
    assert row.forcing.precipitation_mm_day == 5.0
    assert row.forcing.pet_mm_day == 2.5
    assert row.forcing.source_kind == "reanalysis"
    assert row.flow.discharge_m3s == 3.2
