"""
Unit tests for the FishTracker.

Run with either runner:
    python -m unittest test_fish_tracker
    pytest test_fish_tracker.py

The config is built in memory (ToolConfig(auto_load=False)) so no
tool_config.json is touched, and the tracker is driven with explicit
detections, keeping every test deterministic.
"""

import unittest

from config import ToolConfig
from fish_tracker import FishTracker


def make_tracker(hold=3, gate=0.5) -> FishTracker:
    cfg = ToolConfig(auto_load=False)
    cfg.set("fish_track_hold_frames", hold)
    cfg.set("fish_track_gate_ratio", gate)
    return FishTracker(cfg)


ROI = (100, 100)


class TestDetectionPassthrough(unittest.TestCase):

    def test_first_detection_is_returned(self):
        tr = make_tracker()
        box, status = tr.update((10, 10, 6, 6), ROI)
        self.assertEqual(status, FishTracker.STATUS_DETECTED)
        self.assertEqual(box, (10, 10, 6, 6))
        self.assertTrue(tr.is_tracking)

    def test_close_detections_follow(self):
        tr = make_tracker()
        tr.update((10, 10, 6, 6), ROI)
        box, status = tr.update((14, 12, 6, 6), ROI)
        self.assertEqual(status, FishTracker.STATUS_DETECTED)
        self.assertEqual(box, (14, 12, 6, 6))


class TestCoasting(unittest.TestCase):

    def test_holds_then_loses(self):
        tr = make_tracker(hold=3)
        tr.update((10, 10, 6, 6), ROI)
        # Three misses -> coasting (predicted), tracker stays alive.
        for _ in range(3):
            box, status = tr.update(None, ROI)
            self.assertEqual(status, FishTracker.STATUS_PREDICTED)
            self.assertIsNotNone(box)
            self.assertTrue(tr.is_tracking)
        # Fourth miss exceeds the hold budget -> lost.
        box, status = tr.update(None, ROI)
        self.assertEqual(status, FishTracker.STATUS_LOST)
        self.assertIsNone(box)
        self.assertFalse(tr.is_tracking)

    def test_hold_zero_loses_immediately(self):
        tr = make_tracker(hold=0)
        tr.update((10, 10, 6, 6), ROI)
        box, status = tr.update(None, ROI)
        self.assertEqual(status, FishTracker.STATUS_LOST)
        self.assertIsNone(box)

    def test_coast_prediction_moves_with_velocity(self):
        tr = make_tracker(hold=5)
        tr.update((10, 10, 6, 6), ROI)
        tr.update((16, 10, 6, 6), ROI)   # moving +x
        box, status = tr.update(None, ROI)
        self.assertEqual(status, FishTracker.STATUS_PREDICTED)
        # Coasting continues rightward, not stuck at the last x.
        self.assertGreater(box[0], 16)


class TestGate(unittest.TestCase):

    def test_far_outlier_is_rejected_while_fresh(self):
        tr = make_tracker(hold=5, gate=0.1)   # small gate
        tr.update((10, 10, 6, 6), ROI)
        # A detection on the far side of the ROI is an outlier -> coast instead.
        box, status = tr.update((90, 90, 6, 6), ROI)
        self.assertEqual(status, FishTracker.STATUS_PREDICTED)
        self.assertLess(box[0], 30)   # stayed near the track, not at 90

    def test_reacquires_after_hold_budget(self):
        tr = make_tracker(hold=2, gate=0.1)
        tr.update((10, 10, 6, 6), ROI)
        tr.update(None, ROI)   # miss 1 -> coast
        tr.update(None, ROI)   # miss 2 -> coast (misses now == hold)
        # A far detection now re-acquires instead of being gated forever.
        box, status = tr.update((90, 90, 6, 6), ROI)
        self.assertEqual(status, FishTracker.STATUS_DETECTED)
        self.assertEqual(box, (90, 90, 6, 6))


class TestReset(unittest.TestCase):

    def test_reset_clears_track(self):
        tr = make_tracker()
        tr.update((10, 10, 6, 6), ROI)
        self.assertTrue(tr.is_tracking)
        tr.reset()
        self.assertFalse(tr.is_tracking)
        # After reset the next detection starts a fresh track.
        box, status = tr.update((50, 50, 6, 6), ROI)
        self.assertEqual(status, FishTracker.STATUS_DETECTED)
        self.assertEqual(box, (50, 50, 6, 6))


if __name__ == "__main__":
    unittest.main()
