import math
import random
import logging
from typing import Optional, Tuple, Callable

from config import ToolConfig

_logger = logging.getLogger("CatchTrigger")


class CatchTrigger:
    """
    Decides, from vision only, when the "catch" moment is.

    Game mechanic: the fish is catchable as soon as it is reachable inside the
    target circle (or on its ring, which has a small hitbox) - whether it is
    standing still or darting through. The trigger must:

      - fire while the fish is in the circle, moving OR still,
      - fire at most ONCE per entry (not every frame it stays in the circle),
      - fire at a RANDOM point during that pass, not always the instant the
        fish becomes reachable.

    It emits a boolean trigger per frame reporting when a click would be
    warranted. It does NOT click anything - it only reports the moment.

    Randomness is a per-frame fire probability while armed and in the zone: the
    first "hit" fires and disarms until the fish leaves the zone, giving a
    single, randomly-timed trigger per pass. An injectable rng keeps it testable.
    """

    def __init__(self, config: Optional[ToolConfig] = None,
                 rng: Optional[Callable[[], float]] = None):
        """
        Args:
            config (ToolConfig, optional): Provides the CATCH parameters.
            rng (callable, optional): Returns a float in [0, 1). Defaults to
                random.random; inject a deterministic one for tests.
        """
        cfg = config if config is not None else ToolConfig()
        self.__hitbox_frac = cfg.get("circle_hitbox_frac")
        self.__fire_prob = cfg.get("trigger_fire_prob")
        self.__rng = rng if rng is not None else random.random
        self.reset()

    def reset(self) -> None:
        """Re-arms the trigger (call when the fishing episode ends)."""
        # Armed = ready to fire once for the current / next circle entry.
        self.__armed = True

    def __in_zone(self, fish_center, circle) -> bool:
        """True if the fish center is inside the circle or on its ring hitbox."""
        if fish_center is None or circle is None:
            return False
        cx, cy, r = circle
        dist = math.hypot(fish_center[0] - cx, fish_center[1] - cy)
        return dist <= r * (1.0 + self.__hitbox_frac)

    def update(self, fish_center: Optional[Tuple[float, float]],
               circle: Optional[Tuple[float, float, float]],
               alive: bool,
               roi_size: Optional[Tuple[int, int]] = None) -> bool:
        """
        Advances the trigger by one frame.

        Args:
            fish_center (tuple|None): (cx, cy) of the tracked fish, or None.
            circle (tuple|None): (cx, cy, r) of the target ring, or None.
            alive (bool): True if the fish track exists this frame.
            roi_size (tuple|None): Unused; kept for call-site symmetry.

        Returns:
            bool: True on the single, randomly-timed trigger for this pass.
        """
        if not (alive and self.__in_zone(fish_center, circle)):
            # Fish not reachable -> re-arm for the next entry.
            self.__armed = True
            return False

        # In the catch zone.
        if not self.__armed:
            return False  # already fired once for this pass

        # Randomly timed single fire while the fish is in reach.
        if self.__rng() < self.__fire_prob:
            self.__armed = False
            return True
        return False
