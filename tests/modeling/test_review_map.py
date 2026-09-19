from pathlib import Path

from hydro_agent.modeling.review_map import (
    build_unit_candidate_review_payload,
    render_basin_review_map,
    write_units_geojson,
)


def test_render_basin_review_map_writes_svg(tmp_path: Path):
    gis = tmp_path / "gis"
    gis.mkdir()
    (gis / "boundary.geojson").write_text(
        """{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},
        "geometry":{"type":"Polygon","coordinates":[[[-89.5,31.5],[-89.2,31.5],[-89.2,31.8],[-89.5,31.8],[-89.5,31.5]]]}}]}""",
        encoding="utf-8",
    )
    (gis / "outlet.geojson").write_text(
        """{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},
        "geometry":{"type":"Point","coordinates":[-89.4,31.7]}}]}""",
        encoding="utf-8",
    )
    (gis / "flowlines.geojson").write_text(
        """{"type":"FeatureCollection","features":[
        {"type":"Feature","properties":{},"geometry":{"type":"LineString","coordinates":[[-89.45,31.75],[-89.4,31.7],[-89.35,31.65]]}},
        {"type":"Feature","properties":{},"geometry":{"type":"LineString","coordinates":[[-89.42,31.78],[-89.4,31.7]]}}
        ]}""",
        encoding="utf-8",
    )
    (gis / "units.csv").write_text("unit_id,area_km2,source\n1,10,a\n2,10,b\n", encoding="utf-8")
    out = render_basin_review_map(gis, title="Leaf River")
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "svg" in text
    assert "出口" in text
    assert "河网" in text
    assert "计算单元" in text
    assert "#0A84FF" in text  # river stroke
    assert (gis / "units.geojson").is_file()


def test_write_units_geojson_sectors(tmp_path: Path):
    gis = tmp_path / "gis"
    gis.mkdir()
    (gis / "boundary.geojson").write_text(
        """{"type":"FeatureCollection","features":[{"type":"Feature","properties":{},
        "geometry":{"type":"Polygon","coordinates":[[[-89.5,31.5],[-89.2,31.5],[-89.2,31.8],[-89.5,31.8],[-89.5,31.5]]]}}]}""",
        encoding="utf-8",
    )
    out = write_units_geojson(gis, unit_count=4, outlet_xy=(-89.4, 31.7))
    assert out is not None and out.is_file()
    payload = out.read_text(encoding="utf-8")
    assert '"unit_id": 1' in payload or '"unit_id":1' in payload



def test_candidate_review_payload_references_existing_geometry_without_embedding_it():
    candidates = [
        {
            "candidate_id": "units-lumped-a",
            "kind": "lumped",
            "unit_ids": ["basin"],
            "unit_count": 1,
            "area_distribution_km2": [20.0],
            "evidence_refs": ["drainage.area_km2"],
        },
        {
            "candidate_id": "units-topology-b",
            "kind": "topology_subbasin",
            "unit_ids": ["1", "2"],
            "unit_count": 2,
            "area_distribution_km2": [8.0, 12.0],
            "evidence_refs": ["topology.unit_ids"],
        },
        {
            "candidate_id": "units-heterogeneity-c",
            "kind": "heterogeneity_aware",
            "unit_ids": ["1", "2"],
            "unit_count": 2,
            "area_distribution_km2": [8.0, 12.0],
            "evidence_refs": ["elevation.std", "topology.unit_ids"],
        },
    ]

    payload = build_unit_candidate_review_payload(candidates)

    assert payload[0]["geometry_source"] == "boundary.geojson"
    assert payload[1]["geometry_source"] == "units.geojson"
    assert payload[2]["geometry_source"] == "units.geojson"
    assert all("geometry" not in item for item in payload)
    assert payload[1]["unit_ids"] == ["1", "2"]
