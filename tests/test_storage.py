from home_energy_dashboard.storage import Storage
from home_energy_dashboard.tesla import LiveSample


def _sample(grid: float) -> LiveSample:
    return LiveSample(solar_kw=5.0, home_kw=1.0, grid_kw=grid, battery_kw=0.0, battery_soc=80.0)


def test_recent_and_since_helpers(tmp_path) -> None:
    store = Storage(str(tmp_path / "t.sqlite3"))
    store.initialize()
    for grid in (1.0, 2.0, 3.0):
        store.save_sample(123, _sample(grid))

    recent = store.recent_samples(limit=2)
    assert len(recent) == 2
    # Oldest first within the window; the two most recent are grid 2.0 then 3.0.
    assert [r["grid_kw"] for r in recent] == [2.0, 3.0]

    all_since = store.samples_since("2000-01-01T00:00:00+00:00")
    assert len(all_since) == 3
    assert [r["grid_kw"] for r in all_since] == [1.0, 2.0, 3.0]

    none_since = store.samples_since("2999-01-01T00:00:00+00:00")
    assert none_since == []
