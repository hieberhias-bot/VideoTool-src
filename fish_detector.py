import logging
from typing import Optional, Tuple

import cv2
import numpy as np

from config import ToolConfig
from image_utils import clean_mask

_logger = logging.getLogger("FishDetector")


class FishDetector:
    """
    Locates the fish silhouette inside the fishing-window ROI.

    The fish is a faint, low-contrast target, so a single cue is unreliable.
    This detector combines two:

      - darkness: the fish is darker than the bright water (V <= value_max),
      - motion:   the fish moves while the water only shimmers, captured by a
        MOG2 background subtractor.

    Using the intersection (dark AND moving) removes the bright animated target
    circle and the shimmer - both are bright - and isolates the moving dark
    fish, which keeps the detector precise. Precision matters because the result
    feeds a temporal tracker: a false blob near the track would hijack it.

    While the motion model is still warming up (or when motion is disabled via
    config) the detector falls back to darkness only. It is stateful (the MOG2
    history) so reset() must be called whenever the fishing window disappears.

    Every crop is normalized to a fixed canonical size before processing. The
    multi-scale window matcher returns crops whose size (and slightly, position)
    jitter frame to frame; MOG2 needs dimensionally stable input, so working on
    a canonical size keeps the background model coherent. Detected boxes are
    scaled back to the original crop's coordinates.
    """

    # Canonical working size (roughly the fishing window's aspect ratio).
    CANON_W = 200
    CANON_H = 150

    def __init__(self, config: Optional[ToolConfig] = None):
        """
        Args:
            config (ToolConfig, optional): Provides the fish_* parameters. If
                None a default ToolConfig is loaded.
        """
        cfg = config if config is not None else ToolConfig()
        self.__value_max = cfg.get("fish_value_max")
        self.__min_area_ratio = cfg.get("fish_min_area_ratio")
        self.__band_top = cfg.get("fish_band_top")
        self.__band_bottom = cfg.get("fish_band_bottom")
        self.__use_motion = cfg.get("fish_use_motion")
        self.__warmup = cfg.get("fish_motion_warmup")
        self.reset()

    def reset(self) -> None:
        """Drops the motion history (call when the fishing episode ends)."""
        self.__mog = (cv2.createBackgroundSubtractorMOG2(
            history=120, varThreshold=25, detectShadows=False)
            if self.__use_motion else None)
        self.__seen = 0

    def __build_mask(self, crop: np.ndarray) -> np.ndarray:
        """Builds the fish mask (dark, intersected with motion once warm)."""
        value = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
        dark = cv2.inRange(value, 0, int(self.__value_max))

        if self.__mog is None:
            return dark

        foreground = self.__mog.apply(crop)
        self.__seen += 1
        if self.__seen <= self.__warmup:
            # Motion model not trustworthy yet -> darkness only.
            return dark

        motion = cv2.threshold(foreground, 127, 255, cv2.THRESH_BINARY)[1]
        combined = cv2.bitwise_and(dark, motion)
        return combined

    def detect(self, crop: np.ndarray, debug: bool = False):
        """
        Detects the fish in the given ROI crop.

        Args:
            crop (np.ndarray): The BGR fishing-window crop.
            debug (bool): If true also return a debug visualization.

        Returns:
            Tuple[tuple|None, np.ndarray|None]: (box, debug_image), where box is
                (x, y, w, h) relative to the crop or None if no fish was found.
        """
        h, w = crop.shape[:2]
        # Work on a fixed canonical size so the MOG2 model stays coherent
        # despite the per-frame size jitter of the window crop.
        work = cv2.resize(crop, (self.CANON_W, self.CANON_H),
                          interpolation=cv2.INTER_AREA)
        cw, ch = self.CANON_W, self.CANON_H

        mask = self.__build_mask(work)

        y_lo = int(ch * self.__band_top)
        y_hi = int(ch * self.__band_bottom)
        band = clean_mask(mask[y_lo:y_hi, :])

        contours, _ = cv2.findContours(
            band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        roi_area = cw * ch
        min_area = max(self.__min_area_ratio * roi_area, 1.0)

        best = None
        for c in contours:
            area = cv2.contourArea(c)
            x, y, bw, bh = cv2.boundingRect(c)
            aspect = bw / (bh + 1)
            if area >= min_area and 0.3 < aspect < 3.5:
                if best is None or area > best[0]:
                    best = (area, x, y + y_lo, bw, bh)

        # Scale the canonical-space box back to the original crop coordinates.
        sx, sy = w / cw, h / ch
        box = None
        if best is not None:
            _, x, y, bw, bh = best
            box = (int(x * sx), int(y * sy), int(bw * sx), int(bh * sy))

        if not debug:
            return box, None

        # Debug view in the original crop resolution.
        dbg = crop.copy()
        full = np.zeros((ch, cw), np.uint8)
        full[y_lo:y_hi, :] = band
        full = cv2.resize(full, (w, h), interpolation=cv2.INTER_NEAREST)
        dbg[full > 0] = (0, 255, 0)
        if box is not None:
            x, y, bw, bh = box
            cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
        return box, dbg
