from datetime import date

from hydro_agent.models.forcing import basin_latitude_deg, seasonal_temperature_c


def test_yaogu_latitude_and_seasonal_temperature():
    assert basin_latitude_deg({"basin_id": "yaogu"}) == 22.9
    january = seasonal_temperature_c(date(2000, 1, 15), latitude=22.9)
    july = seasonal_temperature_c(date(2000, 7, 15), latitude=22.9)
    assert january > 10
    assert july > january
    assert july < 40
