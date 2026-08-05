import cv2
from typing import Tuple
from numpy import ndarray
import numpy as np
from screen import GeneralCapture
from image_utils import (get_image_template, detect_dark_object, detect_circle,
                         overlay_image, hsv_mask, clean_mask)
import math
from tool_config import ToolConfig
from fish_tracker import FishTracker
from fish_detector import FishDetector
from catch_trigger import CatchTrigger
import logging
import time
import os

_logger = logging.getLogger("VisionProcessor")


class VisionProcessor():

    """
    Class responsible for detecting the fish game window, the fish position and the circle.
    """
    # GAME MATCH TEMPLATE PATH
    GAME_TEMPLATE_PATH = os.path.join("resources","border_template.png")

    # Match template threshold
    GAME_THRESHOLD = 0.7

    # BORDER CROP
    BORDER_OFFSET = 10
    BORDER_OFFSET_TITLE = 28

    def __init__(self, lower_scale=1, higher_scale=1, num_templates_searches=1, debug=False, resize_factor=0.3, config: ToolConfig = None):
        """
        Initialize the VisionProcessor class

        Args:
            lower_scale (int, optional): The lower scale/ratio of each screenshot to be used on get_image_template. Defaults to 1.
            higher_scale (int, optional): The higher scale/ratio of each screenshot to be used on get_image_template. Defaults to 1.
            num_templates_searches (int, optional): The number of templates searches to be done between lower_scale abd higher_scale. Defaults to 1.
            debug (bool, optional): If debug mode should be used. Defaults to False.
            resize_factor (float, optional): The resize factor that should be applied before the processing (Currently only used in matchTemplate). Defaults to 0.3.
            config (ToolConfig, optional): Configuration providing the HSV color
                detection parameters. If None a default ToolConfig is loaded.
                Defaults to None.
        """
        # Match template related
        self.__lower_scale = lower_scale
        self.__higher_scale = higher_scale
        self.__num_templates_searches = num_templates_searches
        self.__resize_factor = resize_factor
        # Template to be matched
        self.__template_game: ndarray = cv2.imread(
            str(self.GAME_TEMPLATE_PATH))
        # Apply smoothing for better results
        self.__template_game = cv2.bilateralFilter(
            self.__template_game, 7, 85, 85)

        # Color detection parameters (read from the tool config).
        self.__config = config if config is not None else ToolConfig()
        self.__load_color_params()

        # Fish detector (darkness + optional motion) and the temporal tracker
        # that bridges missed frames into a continuous fish position.
        self.__fish_detector = FishDetector(self.__config)
        self.__fish_tracker = FishTracker(self.__config)
        # Catch trigger (in-circle + paused). Detection only, never clicks.
        self.__catch_trigger = CatchTrigger(self.__config)
        # Diagnostics (updated every frame the window is present).
        self.last_raw_found = False
        self.last_track_status = FishTracker.STATUS_LOST
        self.last_circle = None          # (cx, cy, r) in crop coords or None
        self.last_fish_in_circle = False
        self.last_catch_trigger = False

        # Debug related
        self.__debug = debug
        self.__dbg_image: ndarray = None

    def __load_color_params(self) -> None:
        """
        Loads the HSV color detection parameters from the configuration into
        instance attributes. Call again after the config changed to pick up
        new values without recreating the processor.
        """
        c = self.__config
        # Multi-scale template search bounds (resolution independence).
        self.__lower_scale = c.get("template_scale_min")
        self.__higher_scale = c.get("template_scale_max")
        self.__num_templates_searches = c.get("template_scale_steps")
        # Bite indicator ("grab")
        self.__grab_hue_target = c.get("grab_hue_target")
        self.__grab_hue_tolerance = c.get("grab_hue_tolerance")
        self.__grab_sat_min = c.get("grab_sat_min")
        self.__grab_val_min = c.get("grab_val_min")
        self.__grab_min_area_ratio = c.get("grab_min_area_ratio")
        # Fish silhouette (dark object on bright water -> brightness based)
        self.__fish_value_max = c.get("fish_value_max")
        self.__fish_min_area_ratio = c.get("fish_min_area_ratio")
        self.__fish_band_top = c.get("fish_band_top")
        self.__fish_band_bottom = c.get("fish_band_bottom")
        # Target circle
        self.__circle_r_min = c.get("circle_radius_min_frac")
        self.__circle_r_max = c.get("circle_radius_max_frac")
        self.__circle_sensitivity = c.get("circle_sensitivity")

    def __get_fish_pos(self, img_crop: ndarray) -> Tuple[int, int, int, int, bool, ndarray]:
        """
        Get the raw per-frame fish position via the FishDetector (darkness +
        optional motion).

        Args:
            img_crop (ndarray): The cropped fishing game image

        Returns:
            Tuple[int,int,int,int,bool,ndarray]: x,y,width,height,found,debug_mask
        """
        box, dbg_img = self.__fish_detector.detect(img_crop, debug=self.__debug)
        if dbg_img is None:
            dbg_img = img_crop
        if box is None:
            return 0, 0, 0, 0, False, dbg_img
        x, y, w, h = box
        return x, y, w, h, True, dbg_img

    def __get_circle_fishable_ratio(self, cropped: ndarray) -> Tuple[ndarray, float]:
        """
        Builds the HSV mask for the bite indicator ("grab") and returns it
        together with the fraction of the ROI that is lit up. Using a ratio
        instead of an absolute pixel sum makes the threshold independent of the
        window resolution and the resize_factor.

        Args:
            cropped (ndarray): The cropped fishing game image

        Returns:
            Tuple[ndarray,float]: The cleaned mask and the lit-up area ratio
                (lit pixels / ROI area), in range 0.0 - 1.0.
        """
        mask = hsv_mask(cropped, self.__grab_hue_target, self.__grab_hue_tolerance,
                        self.__grab_sat_min, self.__grab_val_min)
        mask = clean_mask(mask)

        roi_area = cropped.shape[0] * cropped.shape[1]
        ratio = (cv2.countNonZero(mask) / roi_area) if roi_area else 0.0

        return mask, ratio

    def get_game_template_crop(self, image: ndarray) -> Tuple[int, int, int, int, float, float]:
        """
        Get the fishing game position and correlation value by using matchTemplate

        Args:
            image (ndarray): Game image

        Returns:
            Tuple[int,int,int,int,float,float]: x,y,width,height,confidence,scale_result
        """
        x, y, width, height, corr, scale = get_image_template(image, self.__template_game,
                                                              high_scale=self.__higher_scale,
                                                              low_scale=self.__lower_scale,
                                                              num_searches=self.__num_templates_searches,
                                                              resize_factor=self.__resize_factor
                                                              )

        start_y = y + self.BORDER_OFFSET + self.BORDER_OFFSET_TITLE
        start_x = x + self.BORDER_OFFSET

        return start_x, start_y, width - self.BORDER_OFFSET*2, height - self.BORDER_OFFSET*2 - self.BORDER_OFFSET_TITLE, corr, scale

    def get_fishing_state(self, image: ndarray) -> Tuple[int, int, int, int, bool, bool, bool]:
        """
        Get the data from the frame.
        Searches for the fishing game, using matchTemplate, and then searches for the fish and the circle, using color range matching.

        Args:
            image (ndarray): The frame to be processed

        Returns:
            Tuple[int,int,int,int,bool,bool,bool]: x,y,width,height,found_circle,found_fish,found_game
        """
        blured_image = cv2.bilateralFilter(image, 7, 85, 85)
        x, y, width, height, corr, scale = self.get_game_template_crop(
            blured_image)

        img_cropped = blured_image[y:y+height, x:x+width]
        # Un-blurred crop for the fish: the silhouette is faint and bilateral
        # filtering washes it out, so darkness detection runs on the raw pixels.
        raw_cropped = image[y:y+height, x:x+width]

        # Checks if the fish game is running
        if corr > self.GAME_THRESHOLD:
            _logger.debug(f"Window state found: corr={corr}")

            # Get the possibility of catch the fish
            circle_mask, fishable_ratio = self.__get_circle_fishable_ratio(
                img_cropped)
            is_fishable = fishable_ratio > self.__grab_min_area_ratio
            _logger.debug(
                f"Fish catchable area_ratio={fishable_ratio:.4f} "
                f"threshold={self.__grab_min_area_ratio} is_fishable={is_fishable}")

            # Raw per-frame fish detection (on the un-blurred crop, see above).
            rx, ry, rw, rh, raw_found, dbg_fish_image = self.__get_fish_pos(
                raw_cropped)

            # Feed the raw detection through the temporal tracker so the fish
            # position stays continuous across the frames where the faint
            # silhouette is missed.
            detection = (rx, ry, rw, rh) if raw_found else None
            tracked, track_status = self.__fish_tracker.update(
                detection, roi_size=(width, height))

            if tracked is not None:
                x_fish, y_fish, w_fish, h_fish = tracked
                detected_fish = True
            else:
                x_fish = y_fish = w_fish = h_fish = 0
                detected_fish = False

            # Detect the target ring and test whether the (tracked) fish sits
            # inside it - the geometric basis for a "now catchable" decision.
            circle = detect_circle(
                raw_cropped, self.__circle_r_min, self.__circle_r_max,
                self.__circle_sensitivity)
            fish_center = None
            fish_in_circle = False
            if detected_fish:
                fish_center = (x_fish + w_fish / 2.0, y_fish + h_fish / 2.0)
                if circle is not None:
                    cx, cy, r = circle
                    fish_in_circle = math.hypot(
                        fish_center[0] - cx, fish_center[1] - cy) <= r

            # Catch trigger: fish reachable in the circle/ring (moving or still),
            # fired at most once per entry at a random moment. Detection only -
            # it reports when a click would be warranted, it does not click.
            catch = self.__catch_trigger.update(
                fish_center, circle, detected_fish,
                roi_size=(width, height))

            # Diagnostics: raw per-frame detection vs. tracked (continuous).
            self.last_raw_found = raw_found
            self.last_track_status = track_status
            self.last_circle = circle
            self.last_fish_in_circle = fish_in_circle
            self.last_catch_trigger = catch
            _logger.debug(
                f"Fish at x:{x_fish} y:{y_fish} w:{w_fish} h:{h_fish} "
                f"track={track_status} raw={raw_found} in_circle={fish_in_circle}")

            # Save a debug image with the view of the algorithm
            if self.__debug:
                self.__dbg_image = cv2.blur(image, (8, 8))

                if is_fishable:
                    dbg_fish_image[circle_mask > 0] = (0, 155, 0)
                else:
                    dbg_fish_image[circle_mask > 0] = (0, 0, 155)

                # Draw the target ring (green if the fish is inside it, else red).
                if circle is not None:
                    cx, cy, r = (int(v) for v in circle)
                    ring_color = (0, 255, 0) if fish_in_circle else (0, 0, 255)
                    cv2.circle(dbg_fish_image, (cx, cy), r, ring_color, 1)

                # Draw the tracked box: cyan when backed by a live detection,
                # yellow while coasting through a dropout.
                if tracked is not None:
                    color = (255, 255, 0) if track_status == "detected" \
                        else (0, 255, 255)
                    cv2.rectangle(dbg_fish_image, (x_fish, y_fish),
                                  (x_fish + w_fish, y_fish + h_fish), color, 1)

                # A catch trigger: solid magenta dot at the fish center.
                if catch and fish_center is not None:
                    cv2.circle(dbg_fish_image,
                               (int(fish_center[0]), int(fish_center[1])),
                               4, (255, 0, 255), -1)

                self.__dbg_image = overlay_image(
                    self.__dbg_image, dbg_fish_image, x, y)

            return x_fish+x, y_fish+y, w_fish, h_fish, is_fishable, detected_fish, True

        else:
            # Window gone -> the fishing episode ended. Drop the motion model
            # and the track so a new episode starts fresh instead of coasting
            # onto stale positions.
            self.__fish_detector.reset()
            self.__fish_tracker.reset()
            self.__catch_trigger.reset()
            self.last_raw_found = False
            self.last_track_status = FishTracker.STATUS_LOST
            self.last_circle = None
            self.last_fish_in_circle = False
            self.last_catch_trigger = False

            if self.__debug:
                self.__dbg_image = cv2.blur(image, (8, 8))
                self.__dbg_image = overlay_image(
                    self.__dbg_image, img_cropped, x, y)

            _logger.debug(f"Could not find the game window, corr={corr}")

            return 0, 0, 0, 0, False, False, False

    def get_debug_frame(self) -> ndarray:
        """
        Get an image related to the last frame processed.
        Only available if debug was passed as True in the constructor.

        Returns:
            ndarray: A debug image with information about the last vision.
        """
        if self.__debug:
            return self.__dbg_image
        else:
            return None


__last_time = time.time()


def __show_preview(frame, fish_vision):
    """
    Function intended only for debug purposes.
    """
    global __last_time

    _logger.debug(f'Frame size shape: {frame.shape}')
    x, y, w, h, fishable, fish_detectable, game_on = fish_vision.get_fishing_state(
        frame)

    curr_time = time.time()
    delta_time = curr_time-__last_time

    print(f'FPS:{int(1/delta_time)}')

    dbg_frame = fish_vision.get_debug_frame()
    if dbg_frame is not None:
        cv2.imshow("Vision-dbg", dbg_frame)

    if game_on:
        cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 0, 255), 2)

    cv2.imshow("Vision", frame)

    __last_time = curr_time
    if cv2.waitKey(1) == 27:
        return False

    return True


def main():
    import argparse
    logging.basicConfig(
        level=logging.INFO, format="[%(asctime)s][%(levelname)s] - %(message)s", datefmt="%H:%M:%S")
    _logger.setLevel(logging.DEBUG)

    # Parse args
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', type=str)
    parser.add_argument('--window', type=str)
    parser.add_argument('--debug', nargs='?',
                        default=False, const=True, type=bool)
    parser.add_argument('--resize_factor', type=float, default=0.3,
                        help="Downscale factor before processing (<=1). "
                             "1 = full resolution (more accurate, slower).")
    parser.add_argument('--realtime', nargs='?', default=False, const=True,
                        type=bool,
                        help="Play the video at its true speed, dropping frames "
                             "that can't be processed in time.")
    args = parser.parse_args()

    fish_vision = VisionProcessor(
        debug=args.debug, resize_factor=args.resize_factor)

    if args.video:
        # Open video

        _logger.info(f"Running tests in video {args.video}")
        cap = cv2.VideoCapture(args.video)
        if not cap.isOpened():
            raise Exception(f"Fail to open video: {args.video}")

        if args.realtime:
            # Real-time playback: stay in sync with the wall clock and drop the
            # frames we can't process in time, so the video plays at its true
            # speed while tracking runs at the effective processing rate.
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            start = time.time()
            frame_idx = 0          # frames consumed from the file so far
            while 1:
                # Which frame should be shown "now" at real speed.
                target = int((time.time() - start) * src_fps)
                if target <= frame_idx:
                    # Ahead of schedule: wait briefly instead of busy-looping.
                    if cv2.waitKey(1) == 27:
                        break
                    continue
                # Skip (grab without decoding) to catch up to real time.
                ret = True
                while frame_idx < target - 1 and ret:
                    ret = cap.grab()
                    frame_idx += 1
                ret, frame = cap.read()
                frame_idx += 1
                if not ret:
                    break
                if not __show_preview(frame, fish_vision):
                    break
        else:
            # As-fast-as-possible: process every frame (not real-time).
            while 1:
                ret, frame = cap.read()

                if not ret:
                    break

                if not __show_preview(frame, fish_vision):
                    break

    elif args.window:
        _logger.info(f"Running tests in window {args.window}")

        wnd_capture = GeneralCapture()
        wnd_capture.set_window_name(args.window)

        while 1:
            frame, x, y = wnd_capture.get_screenshot()
            if frame is None:
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            if frame is not None:
                if not __show_preview(frame, fish_vision):
                    break

    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
