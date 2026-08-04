"""
Unit tests for the PauseManager.

Run with either runner:
    python -m unittest test_pause_manager
    pytest test_pause_manager.py

The tests build the configuration in memory (ToolConfig(auto_load=False)) so no
tool_config.json is touched, and drive the manager with a fixed dt instead of
real time, keeping every test deterministic and independent of the rest of the
tool.
"""

import random
import unittest

from config import ToolConfig
from pause_manager import PauseManager


def make_config(pause_enabled=True, work_min=1, work_max=2,
                pause_min=10, pause_max=20) -> ToolConfig:
    """
    Builds an in-memory ToolConfig with the given PAUSES values.

    Args:
        pause_enabled (bool): Whether pausing is enabled.
        work_min (int): Minimum work time in minutes.
        work_max (int): Maximum work time in minutes.
        pause_min (int): Minimum pause duration in seconds.
        pause_max (int): Maximum pause duration in seconds.

    Returns:
        ToolConfig: A config that was never loaded from / saved to disk.
    """
    cfg = ToolConfig(auto_load=False)
    cfg.set("pause_enabled", pause_enabled)
    cfg.set("work_minutes_min", work_min)
    cfg.set("work_minutes_max", work_max)
    cfg.set("pause_seconds_min", pause_min)
    cfg.set("pause_seconds_max", pause_max)
    return cfg


def collect_segments(pm: PauseManager, steps: int, dt: float = 1.0) -> list:
    """
    Advances the manager `steps` times by dt seconds and records the length of
    every completed phase.

    With integer-second durations and dt=1.0 the phase boundaries fall exactly
    on a step, so the measured segment length equals the real phase duration.

    Args:
        pm (PauseManager): The manager to drive.
        steps (int): Number of update() calls.
        dt (float): Simulated time per step, in seconds.

    Returns:
        list: A list of (state, duration_seconds) tuples for each completed phase.
    """
    segments = []
    prev = pm.state
    seg = 0.0
    for _ in range(steps):
        pm.update(dt)
        seg += dt
        if pm.state != prev:
            segments.append((prev, seg))
            seg = 0.0
            prev = pm.state
    return segments


class TestRandomizationBounds(unittest.TestCase):
    """Randomized work/pause durations must always respect the config bounds."""

    def test_durations_within_bounds(self):
        random.seed(1)
        cfg = make_config(work_min=1, work_max=3, pause_min=10, pause_max=20)
        pm = PauseManager(cfg)

        segments = collect_segments(pm, steps=5000, dt=1.0)
        works = [d for state, d in segments if state == PauseManager.STATE_WORKING]
        pauses = [d for state, d in segments if state == PauseManager.STATE_PAUSING]

        # The run is long enough to contain several full cycles.
        self.assertTrue(works, "expected at least one completed work phase")
        self.assertTrue(pauses, "expected at least one completed pause phase")

        for d in works:
            self.assertGreaterEqual(d, 1 * 60)
            self.assertLessEqual(d, 3 * 60)
        for d in pauses:
            self.assertGreaterEqual(d, 10)
            self.assertLessEqual(d, 20)

    def test_min_equals_max_is_deterministic(self):
        # When min == max there is only one possible duration.
        cfg = make_config(work_min=5, work_max=5, pause_min=30, pause_max=30)
        pm = PauseManager(cfg)

        self.assertEqual(pm.time_until_next_event(), 5 * 60)

        for state, d in collect_segments(pm, steps=5000, dt=1.0):
            expected = 300 if state == PauseManager.STATE_WORKING else 30
            self.assertEqual(d, expected)


class TestStateTransitions(unittest.TestCase):
    """The state machine must cycle working -> pausing -> working in order."""

    def test_cycle_order(self):
        cfg = make_config(work_min=1, work_max=1, pause_min=5, pause_max=5)
        pm = PauseManager(cfg)

        # Starts working.
        self.assertEqual(pm.state, PauseManager.STATE_WORKING)
        self.assertFalse(pm.is_pausing())

        # After the 60 s work phase -> pausing.
        pm.update(60)
        self.assertEqual(pm.state, PauseManager.STATE_PAUSING)
        self.assertTrue(pm.is_pausing())

        # After the 5 s pause -> working again.
        pm.update(5)
        self.assertEqual(pm.state, PauseManager.STATE_WORKING)
        self.assertFalse(pm.is_pausing())

    def test_no_premature_transition(self):
        cfg = make_config(work_min=1, work_max=1)
        pm = PauseManager(cfg)

        pm.update(59)  # still inside the 60 s work phase
        self.assertEqual(pm.state, PauseManager.STATE_WORKING)

        pm.update(1)   # exactly at the boundary -> transition
        self.assertEqual(pm.state, PauseManager.STATE_PAUSING)

    def test_time_until_next_event_counts_down(self):
        cfg = make_config(work_min=1, work_max=1)
        pm = PauseManager(cfg)

        self.assertEqual(pm.time_until_next_event(), 60)
        pm.update(20)
        self.assertEqual(pm.time_until_next_event(), 40)

    def test_large_dt_multiple_cycles(self):
        # A dt spanning many cycles must not raise and must stay consistent.
        cfg = make_config(work_min=1, work_max=1, pause_min=5, pause_max=5)
        pm = PauseManager(cfg)

        pm.update(100000)
        self.assertIn(pm.state,
                      (PauseManager.STATE_WORKING, PauseManager.STATE_PAUSING))
        self.assertGreaterEqual(pm.time_until_next_event(), 0)
        self.assertEqual(pm.is_pausing(),
                         pm.state == PauseManager.STATE_PAUSING)


class TestPauseDisabled(unittest.TestCase):
    """With pause_enabled = false the manager must never enter the pause state."""

    def test_never_pauses(self):
        cfg = make_config(pause_enabled=False,
                          work_min=1, work_max=1, pause_min=5, pause_max=5)
        pm = PauseManager(cfg)

        for _ in range(1000):
            pm.update(60)
            self.assertFalse(pm.is_pausing())
            self.assertEqual(pm.state, PauseManager.STATE_WORKING)

    def test_disable_during_pause_resumes_work(self):
        cfg = make_config(pause_enabled=True,
                          work_min=1, work_max=1, pause_min=30, pause_max=30)
        pm = PauseManager(cfg)

        pm.update(60)  # enter pause
        self.assertTrue(pm.is_pausing())

        # Disabling pauses should force the working state on the next update.
        cfg.set("pause_enabled", False)
        pm.update(0)
        self.assertFalse(pm.is_pausing())
        self.assertEqual(pm.state, PauseManager.STATE_WORKING)


class TestReset(unittest.TestCase):
    """reset() returns the manager to a fresh working phase."""

    def test_reset_returns_to_working(self):
        cfg = make_config(work_min=1, work_max=1, pause_min=5, pause_max=5)
        pm = PauseManager(cfg)

        pm.update(60)  # move into pausing
        self.assertTrue(pm.is_pausing())

        pm.reset()
        self.assertEqual(pm.state, PauseManager.STATE_WORKING)
        self.assertFalse(pm.is_pausing())
        self.assertEqual(pm.time_until_next_event(), 60)


if __name__ == "__main__":
    unittest.main()
