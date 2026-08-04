from typing import Tuple
from numpy import ndarray
import numpy as np
import cv2
from typing import Tuple


# https://pyimagesearch.com/2015/01/26/multi-scale-template-matching-using-python-opencv/
def get_image_template(img: ndarray, template: ndarray, low_scale=1.0, high_scale=1.0, num_searches=1, resize_factor=1) -> Tuple[int, int, int, int, float, float]:
    """
    Returns the location where the template has the best match alongside the respective correlation.
    This function will resize the image 'num_searches' times between 'low_scale' and 'high_scale' and returns the best template match. 

    Args:
        img (ndarray): The full image to be cropped.
        template (ndarray): The template image to be searched on img.
        low_scale (float, optional): The lower scale/ratio that the image should be subject to in order to try to match the template. Defaults to 0.2.
        high_scale (float, optional): The higher scale/ratio that the image should be subject to in order to try to match the template. Defaults to 1.4.
        num_searches (int, optional): The number of scale changes should be made. Defaults to 10.
        resize_factor (float, optional): The factor value (0-1) to downsampling the images
    Returns:
        Tuple[int,int,int,int,float,float]: (x, y, width, height, correlation, scale)Tupple containing the cropped image location and the correlation value.
    """
    # Size of original template
    (height, width) = template.shape[:2]

    # loop over the scales of the image
    template = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Resize images if needed
    if resize_factor > 1:
        raise ValueError(
            "Only down-scalling is available, thus the resize value needs to be less then 1")

    elif resize_factor < 1:
        gray = cv2.resize(gray,
                          (int(gray.shape[1]*resize_factor),
                           int(gray.shape[0]*resize_factor)),
                          interpolation=cv2.INTER_AREA)

        template = cv2.resize(template,
                              (int(template.shape[1]*resize_factor),
                               int(template.shape[0]*resize_factor)),
                              interpolation=cv2.INTER_AREA)

    (tH, tW) = template.shape[:2]
    found = None
    for scale in np.linspace(low_scale, high_scale, num_searches)[::-1]:
        # resize the image according to the scale, and keep track
        # of the ratio of the resizing
        resized = cv2.resize(gray,
                             (int(gray.shape[1]*scale),
                              int(gray.shape[0]*scale)),
                             interpolation=cv2.INTER_AREA)
        r = 1/scale

        # if the resized image is smaller than the template, then break
        # from the loop
        if resized.shape[0] < tH or resized.shape[1] < tW:
            break

        result = cv2.matchTemplate(resized, template, cv2.TM_CCOEFF_NORMED)
        #print(f"Time MatchTemplate {(time.time()-start_time)*1000} ms")
        (_, maxVal, _, maxLoc) = cv2.minMaxLoc(result)
        # if we have found a new maximum correlation value, then update
        # the bookkeeping variable
        if found is None or maxVal > found[0]:
            found = (maxVal, maxLoc, r, scale)

    # unpack the bookkeeping variable and compute the (x, y) coordinates
    # of the bounding box based on the resized ratio
    (corr, maxLoc, r, scale) = found
    (startX, startY) = (int(maxLoc[0] * r), int(maxLoc[1] * r))
    (width, height) = (int(width * r), int(height * r))

    # Resize coordinates if needed
    if resize_factor < 1:
        inv_ratio = 1/resize_factor
        (startX, startY) = int(startX*inv_ratio), int(startY*inv_ratio)

    return startX, startY, width, height, corr, scale


def hsv_mask(img: ndarray, hue_target: int, hue_tolerance: int,
             sat_min: int, val_min: int,
             sat_max: int = 255, val_max: int = 255) -> ndarray:
    """
    Builds a binary HSV mask around a target hue with a +/- tolerance.

    The hue channel in OpenCV is circular and ranges from 0 to 179. When the
    tolerance band crosses the 0/179 boundary (typical for reddish tones) the
    range is split into two bands and combined with a logical OR, so wrap-around
    colors are matched correctly.

    Args:
        img (ndarray): The BGR image to search.
        hue_target (int): Target hue (0-179).
        hue_tolerance (int): Allowed hue deviation (+/-).
        sat_min (int): Minimum saturation (0-255).
        val_min (int): Minimum value/brightness (0-255).
        sat_max (int, optional): Maximum saturation. Defaults to 255.
        val_max (int, optional): Maximum value. Defaults to 255.

    Returns:
        ndarray: A single channel uint8 mask (0 or 255).
    """
    into_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    def band(h_lo: int, h_hi: int) -> ndarray:
        lower = np.array([h_lo, sat_min, val_min], dtype=np.uint8)
        upper = np.array([h_hi, sat_max, val_max], dtype=np.uint8)
        return cv2.inRange(into_hsv, lower, upper)

    lo_h = hue_target - hue_tolerance
    hi_h = hue_target + hue_tolerance

    if lo_h < 0:
        # Band wraps below 0: [0, hi_h] OR [180 + lo_h, 179]
        mask = cv2.bitwise_or(band(0, hi_h), band(180 + lo_h, 179))
    elif hi_h > 179:
        # Band wraps above 179: [lo_h, 179] OR [0, hi_h - 180]
        mask = cv2.bitwise_or(band(lo_h, 179), band(0, hi_h - 180))
    else:
        mask = band(lo_h, hi_h)

    return mask


def clean_mask(mask: ndarray, open_ksize: int = 3, close_ksize: int = 5) -> ndarray:
    """
    Cleans a binary mask with morphological opening (removes noise speckles)
    followed by closing (fills small holes).

    Args:
        mask (ndarray): The binary mask.
        open_ksize (int, optional): Kernel size for the opening step. Defaults to 3.
        close_ksize (int, optional): Kernel size for the closing step. Defaults to 5.

    Returns:
        ndarray: The cleaned mask.
    """
    open_kernel = np.ones((open_ksize, open_ksize), np.uint8)
    close_kernel = np.ones((close_ksize, close_ksize), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, open_kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_kernel)
    return mask


def detect_circle(img: ndarray, r_min_frac: float = 0.28, r_max_frac: float = 0.55,
                  sensitivity: int = 35):
    """
    Detects the bright target ring (the fishing circle) inside the ROI via the
    Hough circle transform.

    Args:
        img (ndarray): The BGR fishing-window crop.
        r_min_frac (float): Minimum circle radius as a fraction of ROI height.
        r_max_frac (float): Maximum circle radius as a fraction of ROI height.
        sensitivity (int): Hough accumulator threshold (param2); lower detects
            more (and weaker) circles.

    Returns:
        Tuple[float,float,float] | None: (cx, cy, r) in ROI coordinates, or None.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.medianBlur(gray, 3)

    r_min = max(int(h * r_min_frac), 1)
    r_max = max(int(h * r_max_frac), r_min + 1)

    circles = cv2.HoughCircles(
        gray, cv2.HOUGH_GRADIENT, dp=1.2, minDist=max(h, 1),
        param1=120, param2=sensitivity, minRadius=r_min, maxRadius=r_max)

    if circles is None:
        return None
    # HoughCircles returns the strongest circle first.
    cx, cy, r = circles[0][0]
    return float(cx), float(cy), float(r)


def detect_dark_object(img: ndarray, value_max: int, min_area_ratio: float = 0.0,
                       band_top: float = 0.06, band_bottom: float = 0.84,
                       aspect_min: float = 0.3, aspect_max: float = 3.5,
                       debug: bool = False) -> Tuple[int, int, int, int, ndarray]:
    """
    Finds a dark object (e.g. the fish silhouette) inside a bright ROI by
    thresholding the HSV value channel (darkness), not the hue.

    The search is restricted to a vertical band [band_top, band_bottom] of the
    ROI so the window's title bar (top) and progress bar (bottom) are excluded.
    Candidate blobs are filtered by a minimum area and a plausible aspect ratio
    so wide/thin bars or tiny noise never win; the largest remaining blob is
    returned.

    Args:
        img (ndarray): The BGR ROI (the cropped fishing window).
        value_max (int): Pixels with V <= value_max count as "dark".
        min_area_ratio (float, optional): Minimum blob area as a fraction of the
            ROI area. Defaults to 0.0.
        band_top (float, optional): Top of the search band as a fraction of the
            ROI height. Defaults to 0.06.
        band_bottom (float, optional): Bottom of the search band as a fraction of
            the ROI height. Defaults to 0.84.
        aspect_min (float, optional): Minimum width/height ratio. Defaults to 0.3.
        aspect_max (float, optional): Maximum width/height ratio. Defaults to 3.5.
        debug (bool, optional): If true the last value is a debug image.

    Returns:
        Tuple[int,int,int,int,ndarray]: (x, y, width, height, debug_image), with
            coordinates relative to the full ROI. debug_image is None unless debug.

    Raises:
        ValueError: If no plausible dark object is found.
    """
    h, w = img.shape[:2]
    value = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 2]

    y_lo = int(h * band_top)
    y_hi = int(h * band_bottom)
    band = value[y_lo:y_hi, :]

    mask = cv2.inRange(band, 0, value_max)
    mask = clean_mask(mask)

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    roi_area = w * h
    min_area = max(min_area_ratio * roi_area, 1.0)

    best = None  # (area, x, y, bw, bh) with y already offset to full ROI
    for c in contours:
        area = cv2.contourArea(c)
        x, y, bw, bh = cv2.boundingRect(c)
        aspect = bw / (bh + 1)
        if area >= min_area and aspect_min < aspect < aspect_max:
            if best is None or area > best[0]:
                best = (area, x, y + y_lo, bw, bh)

    if best is None:
        raise ValueError("No dark object found")

    _, x, y, bw, bh = best

    if debug:
        dbg = img.copy()
        # Show the darkness mask (green) in its band and the picked box (red).
        full = np.zeros((h, w), np.uint8)
        full[y_lo:y_hi, :] = mask
        dbg[full > 0] = (0, 255, 0)
        cv2.rectangle(dbg, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
        return x, y, bw, bh, dbg

    return x, y, bw, bh, None


def detect_object_color(img: ndarray, hue_target: int, hue_tolerance: int,
                        sat_min: int, val_min: int,
                        min_contour_area_ratio: float = 0.0,
                        debug: bool = False) -> Tuple[int, int, int, int, ndarray]:
    """
    Returns the bounding box of the biggest object found for the given HSV
    target color. The mask is built with hue wrap-around support and cleaned
    with morphology. Contours smaller than 'min_contour_area_ratio' of the ROI
    are discarded, so isolated noise never wins.

    Args:
        img (ndarray): The BGR image to search.
        hue_target (int): Target hue (0-179).
        hue_tolerance (int): Allowed hue deviation (+/-).
        sat_min (int): Minimum saturation (0-255).
        val_min (int): Minimum value/brightness (0-255).
        min_contour_area_ratio (float, optional): Minimum contour area as a
            fraction of the ROI area. Defaults to 0.0 (no filtering).
        debug (bool, optional): If true the last value returned is a debug image.
            Defaults to False.

    Returns:
        Tuple[int,int,int,int,ndarray]: (x, y, width, height, debug_image). If
            debug is false the last argument is always None.

    Raises:
        ValueError: If no contour matches the color (and passes the area filter).
    """
    mask = hsv_mask(img, hue_target, hue_tolerance, sat_min, val_min)
    mask = clean_mask(mask)

    # Get contours
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Filter out contours that are too small relative to the ROI area.
    roi_area = img.shape[0] * img.shape[1]
    min_area = min_contour_area_ratio * roi_area
    valid = [c for c in contours if cv2.contourArea(c) >= min_area]

    if not valid:
        raise ValueError("No objects found")

    # Get largest contour by area
    largest_cont = max(valid, key=cv2.contourArea)

    # Get a bounding rect
    x, y, w, h = cv2.boundingRect(largest_cont)

    if debug:

        # Get the original image with mask
        res = cv2.bitwise_and(img, img, mask=mask)

        # Draw the contours that passed the area filter
        cv2.drawContours(res, valid, -1, (0, 255, 0), 2)

        # Draw the rectangle on the larger object
        cv2.rectangle(res, (x, y), (x+w, y+h), (0, 0, 255), 3)

        return x, y, w, h, res

    else:

        return x, y, w, h, None


def overlay_image(back_image: ndarray, front_image: ndarray, x_offset: int, y_offset: int) -> ndarray:
    """
    Edit the `back_image` and place the `front_image` on top of it at the specified offset.

    Args:
        back_image (ndarray): The image to be in the back.
        front_image (ndarray): The image to be in the front.
        x_offset (int): The x offset where to start pasting the front_image. 
        y_offset (int): The y offset where to start pasting the front_image.

    Returns:
        ndarray: the back_image edited.
    """
    back_image[y_offset:y_offset+front_image.shape[0],
               x_offset:x_offset+front_image.shape[1]] = front_image

    return back_image
