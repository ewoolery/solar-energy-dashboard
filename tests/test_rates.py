from datetime import datetime
from zoneinfo import ZoneInfo

from home_energy_dashboard import rates


LA = ZoneInfo("America/Los_Angeles")


def test_import_rate_summer_peak_vs_winter_offpeak() -> None:
    summer_peak = datetime(2026, 7, 15, 17, 0, tzinfo=LA)  # 5 PM July -> peak
    winter_offpeak = datetime(2026, 1, 15, 2, 0, tzinfo=LA)  # 2 AM Jan -> off-peak
    assert rates.import_rate(summer_peak) == 0.62
    assert rates.import_rate(winter_offpeak) == 0.36


def test_export_rate_evening_spike_beats_midday() -> None:
    midday = datetime(2026, 7, 15, 13, 0, tzinfo=LA)
    evening = datetime(2026, 7, 15, 19, 0, tzinfo=LA)
    assert rates.export_rate(evening) > rates.export_rate(midday)
    assert rates.export_rate(evening) == 1.15


def test_value_samples_prices_import_and_export_by_local_hour() -> None:
    # Two 12-min intervals: a summer-peak import, then an evening-peak export.
    # The ~1h48m gap between them exceeds MAX_GAP and is skipped.
    samples = [
        {"sampled_at": "2026-07-16T00:00:00+00:00", "grid_kw": 4},   # 17:00 PDT
        {"sampled_at": "2026-07-16T00:12:00+00:00", "grid_kw": 4},
        {"sampled_at": "2026-07-16T02:00:00+00:00", "grid_kw": -6},  # 19:00 PDT
        {"sampled_at": "2026-07-16T02:12:00+00:00", "grid_kw": -6},
    ]
    econ = rates.value_samples(
        samples, tz="America/Los_Angeles", now=datetime(2026, 7, 15, 19, 0, tzinfo=LA)
    ).as_dict()

    assert econ["imported_kwh"] == 0.8        # 4 kW * 0.2 h
    assert econ["exported_kwh"] == 1.2        # 6 kW * 0.2 h
    assert econ["import_cost"] == 0.5         # 0.8 * 0.62 = 0.496 -> 0.50
    assert econ["export_credit"] == 1.38      # 1.2 * 1.15
    assert econ["net_value"] == 0.88          # 1.38 - 0.496
    assert econ["current_export_rate"] == 1.15
    assert econ["estimated"] is True


def test_value_samples_empty_is_zeroed() -> None:
    econ = rates.value_samples([], now=datetime(2026, 7, 15, 12, 0, tzinfo=LA)).as_dict()
    assert econ["import_cost"] == 0.0
    assert econ["export_credit"] == 0.0
    assert econ["imported_kwh"] == 0.0
