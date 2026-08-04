import random
import logging
from typing import Optional

from config import ToolConfig

_logger = logging.getLogger("PauseManager")


class PauseManager:
    """
    Tracks alternating work/pause cycles based on the PAUSES configuration.

    The manager is a pure time state machine: it does not sleep, capture time
    itself or touch any input. The caller advances it with the elapsed time via
    update(dt) once per iteration and asks is_pausing() whether work should be
    suspended right now. Work and pause durations are re-randomized at the start
    of every cycle, reading the current min/max bounds from the config so live
    config edits take effect on the next cycle.

    States:
        "working" - the tool should run normally.
        "pausing" - the tool should be idle until the pause elapses.
    """

    STATE_WORKING = "working"
    STATE_PAUSING = "pausing"

    def __init__(self, config: Optional[ToolConfig] = None):
        """
        Creates a PauseManager.

        Args:
            config (ToolConfig, optional): Configuration providing the PAUSES
                parameters. If None a default ToolConfig is loaded. Defaults to
                None.
        """
        self.__config = config if config is not None else ToolConfig()
        self.__state = self.STATE_WORKING
        # Seconds remaining in the current phase.
        self.__remaining = self.__pick_work_seconds()

    def __pick_work_seconds(self) -> float:
        """Picks a random work duration (in seconds) from the config bounds."""
        lo = self.__config.get("work_minutes_min")
        hi = self.__config.get("work_minutes_max")
        # min/max guard in case the in-memory config is momentarily inconsistent.
        minutes = random.randint(min(lo, hi), max(lo, hi))
        return minutes * 60.0

    def __pick_pause_seconds(self) -> float:
        """Picks a random pause duration (in seconds) from the config bounds."""
        lo = self.__config.get("pause_seconds_min")
        hi = self.__config.get("pause_seconds_max")
        return float(random.randint(min(lo, hi), max(lo, hi)))

    def __transition(self) -> None:
        """Switches to the other state and randomizes its duration."""
        if self.__state == self.STATE_WORKING:
            self.__state = self.STATE_PAUSING
            self.__remaining = self.__pick_pause_seconds()
            _logger.info(f"Entering pause for {self.__remaining:.0f}s")
        else:
            self.__state = self.STATE_WORKING
            self.__remaining = self.__pick_work_seconds()
            _logger.info(f"Resuming work for {self.__remaining / 60:.1f} min")

    def update(self, dt: float) -> None:
        """
        Advances the manager by dt seconds. Call once per iteration.

        When the current phase's remaining time reaches zero the manager
        transitions to the other state and picks a new random duration, carrying
        over any leftover time so large dt values stay accurate.

        Args:
            dt (float): Elapsed time since the last update, in seconds.
        """
        if dt < 0:
            dt = 0.0

        # If pausing is disabled, force the working state and never pause.
        if not self.__config.get("pause_enabled"):
            if self.__state != self.STATE_WORKING:
                self.__state = self.STATE_WORKING
                self.__remaining = self.__pick_work_seconds()
            return

        self.__remaining -= dt
        # Handle one or more transitions (dt may exceed the remaining time).
        while self.__remaining <= 0:
            carry = -self.__remaining
            self.__transition()
            self.__remaining -= carry

    def is_pausing(self) -> bool:
        """
        Returns:
            bool: True if the tool should currently be paused.
        """
        return self.__state == self.STATE_PAUSING

    def time_until_next_event(self) -> float:
        """
        Returns:
            float: Seconds until the next state change (work<->pause).
        """
        return max(0.0, self.__remaining)

    @property
    def state(self) -> str:
        """
        Returns:
            str: The current state, STATE_WORKING or STATE_PAUSING.
        """
        return self.__state

    def reset(self) -> None:
        """Resets to the working state with a fresh random work duration."""
        self.__state = self.STATE_WORKING
        self.__remaining = self.__pick_work_seconds()
        _logger.debug("PauseManager reset")


if __name__ == "__main__":
    # Simulate a fast-forwarded run so the cycles are visible without waiting.
    logging.basicConfig(level=logging.INFO)
    cfg = ToolConfig()
    cfg.set("pause_enabled", True)
    pm = PauseManager(cfg)

    t = 0.0
    step = 30.0  # simulate 30 s per iteration
    for _ in range(400):
        pm.update(step)
        t += step
        print(f"t={t/60:5.1f} min  state={pm.state:8s} "
              f"next_event_in={pm.time_until_next_event():6.0f}s")
