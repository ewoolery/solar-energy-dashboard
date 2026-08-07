from datetime import datetime, timedelta, timezone

from home_energy_dashboard.tesla import (
    is_expired,
    normalize_live_status,
    stamp_expiry,
    summarize_energy_history,
)


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
    assert sample.grid_kw == -7.5  # negative = exporting (Tesla convention)
    assert sample.battery_kw == 0
    assert sample.battery_soc == 100


def test_stamp_expiry_sets_absolute_deadline_and_keeps_refresh_token() -> None:
    first = stamp_expiry({"access_token": "a", "refresh_token": "r", "expires_in": 28800})
    assert "expires_at" in first
    # A refresh response omitting refresh_token keeps the prior one.
    refreshed = stamp_expiry({"access_token": "b", "expires_in": 28800}, previous=first)
    assert refreshed["refresh_token"] == "r"


def test_is_expired_respects_deadline_and_skew() -> None:
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert is_expired({}) is True  # no expires_at
    assert is_expired({"expires_at": future}) is False
    assert is_expired({"expires_at": past}) is True
    # Within the safety skew, treat as expired.
    edge = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    assert is_expired({"expires_at": edge}, skew=60) is True


def test_summarize_energy_history_aggregates_wh_to_kwh() -> None:
    totals = summarize_energy_history(
        {
            "time_series": [
                {
                    "solar_energy_exported": 40000,
                    "grid_energy_imported": 500,
                    "grid_energy_exported_from_solar": 20000,
                    "grid_energy_exported_from_battery": 5000,
                    "battery_energy_imported_from_solar": 8000,
                    "battery_energy_imported_from_grid": 2000,
                    "battery_energy_exported": 8000,
                    "consumer_energy_imported_from_grid": 500,
                    "consumer_energy_imported_from_solar": 12000,
                    "consumer_energy_imported_from_battery": 7500,
                },
            ]
        }
    )
    assert totals["solar_kwh"] == 40.0
    assert totals["grid_imported_kwh"] == 0.5
    assert totals["grid_exported_kwh"] == 25.0
    assert totals["home_kwh"] == 20.0
    assert totals["battery_charged_kwh"] == 10.0
    assert totals["battery_discharged_kwh"] == 8.0
    # (home - imported) / home = (20 - 0.5) / 20 = 97.5%
    assert totals["self_powered_pct"] == 97.5

