import math
import logging
from typing import Optional, Tuple

from tool_config import ToolConfig

_logger = logging.getLogger("FishTracker")


class FishTracker:
    """
    Temporal tracker that turns per-frame fish detections into a continuous
    track.

    The raw fish detector is unreliable frame to frame (the silhouette is a
    faint, low-contrast target), so this tracker bridges the gaps:

      - a detection close to the predicted position updates the track and
        refreshes a velocity estimate,
      - a missing detection (or one that jumps too far - an outlier) makes the
        track "coast": it keeps moving with a damped velocity for up to
        ``hold_frames`` frames, so the box stays on the fish through short
        dropouts,
      - after ``hold_frames`` consecutive misses the track is dropped and the
        next detection re-acquires it fresh.

    The tracker is a pure state machine: it does not read frames, capture time
    or draw anything. Feed it one detection per frame via ``update`` and read
    the smoothed box back. This makes it deterministic and unit testable.
    """

    STATUS_DETECTED = "detected"
    STATUS_PREDICTED = "predicted"
    STATUS_LOST = "lost"

    def __init__(self, config: Optional[ToolConfig] = None):
        """
        Creates a FishTracker.

        Args:
            config (ToolConfig, optional): Provides ``fish_track_hold_frames``
                and ``fish_track_gate_ratio``. If None a default ToolConfig is
                loaded. Defaults to None.
        """
        cfg = config if config is not None else ToolConfig()
        self.__hold_frames = cfg.get("fish_track_hold_frames")
        self.__gate_ratio = cfg.get("fish_track_gate_ratio")
        self.reset()

    def reset(self) -> None:
        """Drops the current track."""
        self.__box = None            # (x, y, w, h) as floats
        self.__vel = (0.0, 0.0)      # center velocity per frame
        self.__misses = 0

    @property
    def is_tracking(self) -> bool:
        """True while a track (detected or coasting) exists."""
        return self.__box is not None

    @property
    def status(self) -> str:
        """Last status returned by update()."""
        return self.__status if self.__box is not None else self.STATUS_LOST

    @staticmethod
    def __center(box: Tuple[float, float, float, float]) -> Tuple[float, float]:
        x, y, w, h = box
        return x + w / 2.0, y + h / 2.0

    def __accept(self, detection, roi_size):
        """Accepts a detection as the new track state."""
        if self.__box is not None:
            ox, oy = self.__center(self.__box)
            nx, ny = self.__center(detection)
            # Smooth the velocity a little so a single noisy frame can't fling
            # the coast prediction away.
            self.__vel = (0.5 * self.__vel[0] + 0.5 * (nx - ox),
                          0.5 * self.__vel[1] + 0.5 * (ny - oy))
        else:
            self.__vel = (0.0, 0.0)
        self.__box = tuple(float(v) for v in detection)
        self.__misses = 0
        self.__status = self.STATUS_DETECTED
        return self.__as_int(self.__box), self.STATUS_DETECTED

    def __coast(self, roi_size):
        """Moves the track forward with a damped velocity (no detection)."""
        self.__misses += 1
        x, y, w, h = self.__box
        vx, vy = self.__vel
        x += vx
        y += vy
        # Damp the velocity so a coasting track slows to a stop rather than
        # drifting off the screen.
        self.__vel = (vx * 0.8, vy * 0.8)
        if roi_size is not None:
            rw, rh = roi_size
            x = min(max(x, 0.0), max(rw - w, 0.0))
            y = min(max(y, 0.0), max(rh - h, 0.0))
        self.__box = (x, y, w, h)
        self.__status = self.STATUS_PREDICTED
        return self.__as_int(self.__box), self.STATUS_PREDICTED

    def update(self, detection: Optional[Tuple[int, int, int, int]],
               roi_size: Optional[Tuple[int, int]] = None):
        """
        Advances the tracker by one frame.

        Args:
            detection (tuple|None): The raw fish box (x, y, w, h) for this frame,
                or None if the detector found nothing.
            roi_size (tuple|None): (width, height) of the ROI, used to scale the
                association gate and to clamp coasting inside the window.

        Returns:
            Tuple[tuple|None, str]: (box, status). ``box`` is the smoothed
                (x, y, w, h) or None when lost. ``status`` is one of
                STATUS_DETECTED / STATUS_PREDICTED / STATUS_LOST.
        """
        if detection is not None:
            if self.__box is None:
                return self.__accept(detection, roi_size)

            # Gate: reject detections that jump implausibly far from where the
            # track is heading (likely a spurious dark blob), and coast instead.
            px = self.__center(self.__box)[0] + self.__vel[0]
            py = self.__center(self.__box)[1] + self.__vel[1]
            dx_, dy_ = self.__center(detection)
            dist = math.hypot(dx_ - px, dy_ - py)
            gate = self.__gate_dist(roi_size)
            if dist <= gate or self.__misses >= self.__hold_frames:
                # Within gate, or we've coasted long enough that we should trust
                # a fresh detection and re-lock onto it.
                return self.__accept(detection, roi_size)
            # Outlier while the track is still fresh -> coast.
            return self.__miss(roi_size)

        # No detection this frame.
        return self.__miss(roi_size)

    def __miss(self, roi_size):
        """Handles a frame without an accepted detection."""
        if self.__box is not None and self.__misses < self.__hold_frames:
            return self.__coast(roi_size)
        self.reset()
        self.__status = self.STATUS_LOST
        return None, self.STATUS_LOST

    def __gate_dist(self, roi_size) -> float:
        if roi_size is None:
            return float("inf")
        rw, rh = roi_size
        return self.__gate_ratio * math.hypot(rw, rh)

    @staticmethod
    def __as_int(box):
        return tuple(int(round(v)) for v in box)


if __name__ == "__main__":
    # Tiny demo: a detection, a few dropouts (coasting), then loss.
    logging.basicConfig(level=logging.INFO)
    cfg = ToolConfig()
    cfg.set("fish_track_hold_frames", 3)
    tr = FishTracker(cfg)
    seq = [(10, 10, 6, 6), (14, 10, 6, 6), None, None, None, None, (60, 10, 6, 6)]
    for det in seq:
        box, status = tr.update(det, roi_size=(170, 126))
        print(f"det={str(det):18s} -> {status:10s} box={box}")
