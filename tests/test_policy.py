from shelf.policy import LaunchPolicy, Verdict


def started(uptime=3600.0, present=()):
    p = LaunchPolicy()
    p.start(now=0.0, uptime=uptime, drives_with_media=set(present))
    return p


def test_insert_while_running_launches():
    p = started()
    assert p.on_arrival("D:", 100.0) is Verdict.LAUNCH


def test_disc_left_in_at_boot_never_autolaunches():
    p = started(uptime=20.0, present={"D:"})
    assert p.on_arrival("D:", 500.0) is Verdict.PRESENT        # drive re-announces it later
    p.on_removed("D:")
    assert p.on_arrival("D:", 600.0) is Verdict.LAUNCH         # a real re-insert works


def test_slow_drive_after_power_cut():
    # PC booted 20 s ago; the drive reports the disc 60 s after the agent started
    p = started(uptime=20.0)
    assert p.on_arrival("D:", 60.0) is Verdict.PRESENT
    assert p.on_arrival("D:", 400.0) is Verdict.PRESENT        # still the same disc, never removed
    p.on_removed("D:")
    assert p.on_arrival("D:", 410.0) is Verdict.LAUNCH


def test_agent_restart_on_a_long_running_pc_has_short_grace():
    p = started(uptime=10_000.0)
    assert p.on_arrival("D:", 10.0) is Verdict.PRESENT
    assert p.on_arrival("E:", 50.0) is Verdict.LAUNCH


def test_wake_from_sleep():
    p = started()
    p.on_resume(1000.0)
    assert p.on_arrival("D:", 1005.0) is Verdict.PRESENT
    p.on_removed("D:")
    assert p.on_arrival("D:", 1100.0) is Verdict.LAUNCH


def test_debounce_same_disc():
    p = started()
    assert p.should_launch("abc", 100.0)
    assert not p.should_launch("abc", 110.0)
    assert p.should_launch("abc", 200.0)
    assert p.should_launch("other", 110.0)


def test_case_insensitive_letters():
    p = started(present={"d:"})
    assert p.on_arrival("D:", 500.0) is Verdict.PRESENT
