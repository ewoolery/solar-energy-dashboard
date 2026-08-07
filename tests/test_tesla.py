from home_energy_dashboard.tesla import normalize_live_status


def test_normalize_live_status_converts_watts_to_kw() -> None:
    sample = normalize_live_status(
        {
            "solar_power": 7900,
            "load_power": 400,
            "grid_power": -7500,
            "battery_power": 0,
            "percentage_charged": 100,
        }
    )

    assert sample.solar_kw == 7.9
    assert sample.home_kw == 0.4
    assert sample.grid_kw == -7.5
    assert sample.battery_kw == 0
    assert sample.battery_soc == 100

