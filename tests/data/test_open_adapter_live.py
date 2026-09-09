from datetime import date

from hydro_agent.data.adapters.open_basin import (
    LEAF_RIVER,
    fetch_nldi_basin,
    fetch_usgs_site,
    polygon_area_km2_approx,
    polygon_bbox,
)


def test_leaf_river_nldi_and_usgs_live():
    site = fetch_usgs_site(LEAF_RIVER.usgs_site)
    assert abs(site["latitude"] - 31.7069) < 0.01
    assert abs(site["longitude"] + 89.4069) < 0.01
    assert 1500 < site["area_km2"] < 2500
    basin = fetch_nldi_basin(LEAF_RIVER.usgs_site)
    west, south, east, north = polygon_bbox(basin)
    assert west < site["longitude"] < east
    assert south < site["latitude"] < north
    approx = polygon_area_km2_approx(basin, site["latitude"])
    ratio = min(site["area_km2"], approx) / max(site["area_km2"], approx)
    assert ratio >= 0.7


def test_gridmet_scale_sanity_live():
    from hydro_agent.data.adapters.open_basin import fetch_gridmet_forcing

    rows = fetch_gridmet_forcing(
        latitude=31.7069,
        longitude=-89.4069,
        start=date(2020, 1, 1),
        end=date(2020, 1, 7),
    )
    assert len(rows) >= 5
    precip = [r.precipitation_mm_day for r in rows]
    pet = [r.pet_mm_day for r in rows]
    assert all(0 <= p <= 200 for p in precip)
    assert all(0 < e <= 12 for e in pet)
    # After 0.1 scale, Jan PET should be modest (not 15–25 raw packed counts).
    assert sum(pet) / len(pet) < 8.0
