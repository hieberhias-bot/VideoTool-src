"""
Unit tests for the CatchTrigger.

Run with:
    python -m unittest test_catch_trigger
    pytest test_catch_trigger.py

The rng is injected so the random fire timing is deterministic in tests.
"""

import unittest

from config import ToolConfig
from catch_trigger import CatchTrigger

ROI = (100, 100)
CIRCLE = (50.0, 50.0, 20.0)
INSIDE = (50.0, 50.0)          # center of the circle
OUTSIDE = (95.0, 95.0)         # far corner


def make_trigger(rng, hitbox=0.12, fire_prob=0.2):
    cfg = ToolConfig(auto_load=False)
    cfg.set("circle_hitbox_frac", hitbox)
    cfg.set("trigger_fire_prob", fire_prob)
    return CatchTrigger(cfg, rng=rng)


class ConstRng:
    """rng that always returns a fixed value."""
    def __init__(self, v):
        self.v = v

    def __call__(self):
        return self.v


class SeqRng:
    """rng that returns a preset sequence, then its last value forever."""
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def __call__(self):
        v = self.seq[min(self.i, len(self.seq) - 1)]
        self.i += 1
        return v


class TestCatchTrigger(unittest.TestCase):

    def test_fires_once_per_entry(self):
        # rng always 0 -> 0 < 0.2 -> fires on the first in-zone frame.
        tr = make_trigger(ConstRng(0.0))
        self.assertTrue(tr.update(INSIDE, CIRCLE, True, ROI))
        # Still in zone but already fired -> no more triggers.
        self.assertFalse(tr.update(INSIDE, CIRCLE, True, ROI))
        self.assertFalse(tr.update(INSIDE, CIRCLE, True, ROI))

    def test_random_timing_not_always_immediate(self):
        # High rng for two frames (no fire), then low -> fires on the 3rd frame.
        tr = make_trigger(SeqRng([0.9, 0.9, 0.0]))
        self.assertFalse(tr.update(INSIDE, CIRCLE, True, ROI))
        self.assertFalse(tr.update(INSIDE, CIRCLE, True, ROI))
        self.assertTrue(tr.update(INSIDE, CIRCLE, True, ROI))

    def test_triggers_while_moving(self):
        # Different positions each frame (darting through), still inside -> fires.
        tr = make_trigger(ConstRng(0.0))
        moved = (45.0, 50.0)
        self.assertTrue(tr.update(moved, CIRCLE, True, ROI))

    def test_no_trigger_outside(self):
        tr = make_trigger(ConstRng(0.0))
        self.assertFalse(tr.update(OUTSIDE, CIRCLE, True, ROI))

    def test_ring_hitbox_counts_as_in_zone(self):
        tr = make_trigger(ConstRng(0.0))
        on_ring = (50.0 + 22.0, 50.0)   # dist 22 <= 20*1.12 = 22.4
        self.assertTrue(tr.update(on_ring, CIRCLE, True, ROI))

    def test_no_trigger_when_not_alive(self):
        tr = make_trigger(ConstRng(0.0))
        self.assertFalse(tr.update(INSIDE, CIRCLE, False, ROI))

    def test_reentry_fires_again(self):
        tr = make_trigger(ConstRng(0.0))
        self.assertTrue(tr.update(INSIDE, CIRCLE, True, ROI))   # fire, disarm
        self.assertFalse(tr.update(OUTSIDE, CIRCLE, True, ROI))  # leaves -> re-arm
        self.assertTrue(tr.update(INSIDE, CIRCLE, True, ROI))   # new entry fires

    def test_no_circle_no_trigger(self):
        tr = make_trigger(ConstRng(0.0))
        self.assertFalse(tr.update(INSIDE, None, True, ROI))

    def test_reset_rearms(self):
        tr = make_trigger(ConstRng(0.0))
        self.assertTrue(tr.update(INSIDE, CIRCLE, True, ROI))
        self.assertFalse(tr.update(INSIDE, CIRCLE, True, ROI))
        tr.reset()
        self.assertTrue(tr.update(INSIDE, CIRCLE, True, ROI))


if __name__ == "__main__":
    unittest.main()
