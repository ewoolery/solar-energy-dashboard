from home_energy_dashboard.notify import full_edge


def test_fires_once_on_rising_edge_then_holds() -> None:
    armed = True
    # Charging up — no alert until we cross full.
    fire, armed = full_edge(80, armed)
    assert fire is False and armed is True
    # Crosses full: fire once, disarm.
    fire, armed = full_edge(100, armed)
    assert fire is True and armed is False
    # Still sitting full: stays quiet.
    fire, armed = full_edge(100, armed)
    assert fire is False and armed is False


def test_rearms_only_after_dropping_below_rearm_pct() -> None:
    armed = False
    # Slight dip that stays above the re-arm threshold: still disarmed.
    fire, armed = full_edge(97, armed)
    assert fire is False and armed is False
    # Drops below re-arm threshold: re-arm, no alert on the way down.
    fire, armed = full_edge(94, armed)
    assert fire is False and armed is True
    # Next climb to full fires again.
    fire, armed = full_edge(99.6, armed)
    assert fire is True and armed is False


def test_full_pct_boundary_is_inclusive() -> None:
    fire, armed = full_edge(99.5, True, full_pct=99.5)
    assert fire is True and armed is False
