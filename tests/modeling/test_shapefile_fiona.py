from pathlib import Path

import pytest

from hydro_agent.modeling.shapefile_fiona import open as shp_open

GIS = Path(__file__).resolve().parents[2] / 'data/academy/examples/data/GIS图层'

pytestmark = pytest.mark.skipif(not (GIS / '分区.shp').is_file(), reason='academy GIS not present')


def test_shim_reads_academy_boundary_and_stations():
    with shp_open(GIS / '分区.shp', encoding='latin1') as src:
        assert src.crs and 'WGS' in src.crs.upper()
        features = list(src)
        assert len(features) == 1
        geom = features[0]['geometry']
        assert geom['type'] == 'Polygon'
        west, south = min(p[0] for p in geom['coordinates'][0]), min(p[1] for p in geom['coordinates'][0])
        east, north = max(p[0] for p in geom['coordinates'][0]), max(p[1] for p in geom['coordinates'][0])
        assert 111 < west < east < 113
        assert 22 < south < north < 23
    with shp_open(GIS / '流域站网.shp', encoding='latin1') as src:
        codes = []
        for feature in src:
            props = {
                key.encode('latin1').decode('utf-8', errors='replace'): value
                for key, value in feature['properties'].items()
            }
            codes.append(str(props.get('站码')))
            assert feature['geometry']['type'] == 'Point'
            lon, lat = feature['geometry']['coordinates']
            assert 111 < lon < 113
            assert 22 < lat < 24
        assert any(code and code != 'None' for code in codes)
    with shp_open(GIS / '流域河网.shp', encoding='latin1') as src:
        assert src.crs
        rivers = list(src)
        assert len(rivers) == 13
        assert rivers[0]['geometry']['type'] == 'LineString'
