import math

import pytest

from hydro_agent.hydrology.spatial_profile import derive_basin_spatial_profile


def test_spatial_profile_reports_component_statistics_without_single_decision_score():
    profile = derive_basin_spatial_profile(
        elevation_m=[100, 200, 300, 400],
        slope_deg=[2, 5, 20, 35],
        precipitation_mm=[900, 1000, 1300, 1500],
        land_cover={"forest": 0.6, "cropland": 0.4},
        soil={"clay": 0.25, "loam": 0.75},
        drainage={
            "area_km2": 100.0,
            "stream_length_km": 50.0,
            "main_channel_length_km": 20.0,
        },
    )

    assert profile.elevation.mean == pytest.approx(250.0)
    assert profile.elevation.mean_m == pytest.approx(250.0)
    assert profile.precipitation.cv is not None
    assert profile.precipitation.cv > 0
    assert profile.land_cover.fractions["forest"] == pytest.approx(0.6)
    assert profile.drainage.stream_density_km_per_km2 == pytest.approx(0.5)
    assert not hasattr(profile, "recommended_unit_count")
    assert not hasattr(profile, "overall_heterogeneity_score")


def test_missing_land_cover_and_soil_remain_unknown():
    profile = derive_basin_spatial_profile(
        elevation_m=[100, None, 300, float("nan")],
        slope_deg=[2, 5, None],
        precipitation_mm=[900, 1000, 1100],
        land_cover=None,
        soil={},
        drainage={"area_km2": 100.0},
    )

    assert profile.elevation.status == "available"
    assert profile.elevation.count == 2
    assert profile.land_cover.status == "unknown"
    assert profile.land_cover.fractions == {}
    assert profile.soil.status == "unknown"
    assert profile.soil.fractions == {}


def test_categorical_fractions_are_normalized_with_quality_note():
    profile = derive_basin_spatial_profile(
        elevation_m=[100, 200],
        slope_deg=[2, 4],
        precipitation_mm=[900, 1000],
        land_cover={"forest": 60.0, "cropland": 40.0},
        soil={"loam": 1.0},
        drainage={"area_km2": 100.0, "stream_length_km": 25.0},
    )

    assert profile.land_cover.fractions == {
        "cropland": pytest.approx(0.4),
        "forest": pytest.approx(0.6),
    }
    assert "land_cover:fractions_normalized" in profile.evidence_quality


def test_negative_precipitation_is_rejected():
    with pytest.raises(ValueError, match="precipitation"):
        derive_basin_spatial_profile(
            elevation_m=[100, 200],
            slope_deg=[2, 4],
            precipitation_mm=[900, -1],
            land_cover=None,
            soil=None,
            drainage=None,
        )


def test_nonfinite_samples_are_ignored_deterministically():
    first = derive_basin_spatial_profile(
        elevation_m=[100, math.inf, 200, float("nan")],
        slope_deg=[1, 2, 3],
        precipitation_mm=[900, 1000, 1100],
        land_cover={"forest": 1.0},
        soil={"loam": 1.0},
        drainage={"area_km2": 50.0, "stream_length_km": 10.0},
    )
    second = derive_basin_spatial_profile(
        elevation_m=[float("nan"), 200, 100, math.inf],
        slope_deg=[3, 2, 1],
        precipitation_mm=[1100, 900, 1000],
        land_cover={"forest": 1.0},
        soil={"loam": 1.0},
        drainage={"stream_length_km": 10.0, "area_km2": 50.0},
    )

    assert first == second
