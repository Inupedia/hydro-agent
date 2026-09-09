from pathlib import Path

from hydro_agent.modeling.review_map import render_basin_review_map


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
    out = render_basin_review_map(gis, title="Leaf River")
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "svg" in text
    assert "#007AFF" in text
    assert "outlet" in text
