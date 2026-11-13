from home_energy_dashboard.notify import rising_edge


def test_fires_once_on_rising_edge_then_holds() -> None:
    armed = True
    # Charging up — no alert until we cross the threshold.
    fire, armed = rising_edge(80, armed, 99.5, 95.0)
    assert fire is False and armed is True
    # Crosses threshold: fire once, disarm.
    fire, armed = rising_edge(100, armed, 99.5, 95.0)
    assert fire is True and armed is False
    # Still sitting above it: stays quiet.
    fire, armed = rising_edge(100, armed, 99.5, 95.0)
    assert fire is False and armed is False


def test_rearms_only_after_dropping_below_rearm_pct() -> None:
    armed = False
    # Slight dip that stays above the re-arm threshold: still disarmed.
    fire, armed = rising_edge(97, armed, 99.5, 95.0)
    assert fire is False and armed is False
    # Drops below re-arm threshold: re-arm, no alert on the way down.
    fire, armed = rising_edge(94, armed, 99.5, 95.0)
    assert fire is False and armed is True
    # Next climb to full fires again.
    fire, armed = rising_edge(99.6, armed, 99.5, 95.0)
    assert fire is True and armed is False


def test_threshold_boundary_is_inclusive() -> None:
    fire, armed = rising_edge(99.5, True, 99.5, 95.0)
    assert fire is True and armed is False


def test_half_threshold_cycle() -> None:
    # The same detector drives the 50% "safe to plug in" alert (50 / re-arm 40).
    armed = True
    fire, armed = rising_edge(35, armed, 50.0, 40.0)      # overnight low
    assert fire is False and armed is True
    fire, armed = rising_edge(52, armed, 50.0, 40.0)      # climbs past 50
    assert fire is True and armed is False
    fire, armed = rising_edge(80, armed, 50.0, 40.0)      # keeps climbing, quiet
    assert fire is False and armed is False
    fire, armed = rising_edge(38, armed, 50.0, 40.0)      # next night re-arms
    assert fire is False and armed is True
