from hydro_agent.hydrology.spatial_profile import derive_basin_spatial_profile
from hydro_agent.modeling.unit_candidates import build_unit_scheme_candidates


def _profile():
    return derive_basin_spatial_profile(
        elevation_m=[100, 200, 500, 900],
        slope_deg=[2, 5, 15, 30],
        precipitation_mm=[800, 900, 1300, 1500],
        land_cover={"forest": 0.65, "cropland": 0.35},
        soil=None,
        drainage={
            "area_km2": 120.0,
            "stream_length_km": 72.0,
            "main_channel_length_km": 28.0,
        },
    )


def _topology_units():
    return [
        {
            "unit_id": 1,
            "area_km2": 30.0,
            "mean_elevation_m": 180.0,
            "downstream_unit_id": 3,
        },
        {
            "unit_id": 2,
            "area_km2": 25.0,
            "mean_elevation_m": 720.0,
            "downstream_unit_id": 3,
        },
        {
            "unit_id": 3,
            "area_km2": 65.0,
            "mean_elevation_m": 360.0,
            "downstream_unit_id": 0,
        },
    ]


def test_candidate_builder_returns_lumped_topology_and_heterogeneity_options():
    result = build_unit_scheme_candidates(
        spatial_profile=_profile(),
        topology_units=_topology_units(),
        max_units=8,
    )

    assert [item.kind for item in result] == [
        "lumped",
        "topology_subbasin",
        "heterogeneity_aware",
    ]
    assert all(item.unit_count >= 1 for item in result)
    assert all(item.evidence_refs for item in result)
    assert result[0].unit_count == 1
    assert result[1].unit_ids == ("1", "2", "3")
    assert result[2].unit_ids == ("1", "2", "3")
    assert "elevation" in result[2].preserved_contrasts
    assert "precipitation" in result[2].preserved_contrasts
    assert not hasattr(result[2], "polygon")


def test_candidate_ids_and_order_ignore_mapping_iteration_order():
    first = build_unit_scheme_candidates(
        spatial_profile=_profile(),
        topology_units=_topology_units(),
        max_units=8,
    )
    reordered = [
        {
            "downstream_unit_id": row["downstream_unit_id"],
            "mean_elevation_m": row["mean_elevation_m"],
            "area_km2": row["area_km2"],
            "unit_id": row["unit_id"],
        }
        for row in reversed(_topology_units())
    ]
    second = build_unit_scheme_candidates(
        spatial_profile=_profile(),
        topology_units=reordered,
        max_units=8,
    )

    assert first == second


def test_heterogeneity_candidate_is_not_invented_when_spatial_sources_are_unknown():
    profile = derive_basin_spatial_profile(
        elevation_m=None,
        slope_deg=None,
        precipitation_mm=None,
        land_cover=None,
        soil=None,
        drainage={"area_km2": 120.0},
    )

    result = build_unit_scheme_candidates(
        spatial_profile=profile,
        topology_units=_topology_units(),
        max_units=8,
    )

    assert [item.kind for item in result] == ["lumped", "topology_subbasin"]
    assert result[0].lost_contrasts == ()


def test_candidate_builder_never_exceeds_max_units():
    units = [
        {"unit_id": idx, "area_km2": 10.0, "downstream_unit_id": 0}
        for idx in range(1, 13)
    ]

    result = build_unit_scheme_candidates(
        spatial_profile=_profile(),
        topology_units=units,
        max_units=8,
    )

    assert all(item.unit_count <= 8 for item in result)
    assert [item.kind for item in result] == ["lumped"]
