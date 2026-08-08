import sys, os
sys.path.insert(0, r"C:\Users\vm1\Desktop\VideoTool-src")
os.chdir(r"C:\Users\vm1\Desktop\VideoTool-src")
import fish_bot
import cv2
from PIL import ImageGrab
import numpy as np
from modules.fenster import fenster_finden

fenster = fenster_finden("METIN2")
print("Fenster:", fenster)

print("Template geladen:", fish_bot._wurm_template is not None)
if fish_bot._wurm_template is not None:
    th, tw = fish_bot._wurm_template.shape[:2]
    print(f"Template-Groesse: {tw}x{th}")

screenshot = ImageGrab.grab(bbox=(fenster["x"], fenster["y"], fenster["x"]+fenster["w"], fenster["y"]+fenster["h"]))
screenshot_bgr = np.array(screenshot.convert("RGB"))[:, :, ::-1]
cv2.imwrite("screenshot_test.png", screenshot_bgr)
print("Screenshot gespeichert: screenshot_test.png")

h, w = screenshot_bgr.shape[:2]
x0, y0 = int(w * fish_bot.WURM_ROI[0]), int(h * fish_bot.WURM_ROI[1])
x1, y1 = int(w * fish_bot.WURM_ROI[2]), int(h * fish_bot.WURM_ROI[3])
print(f"ROI-Bereich: x {x0}..{x1}, y {y0}..{y1} (Fenster {w}x{h})")
roi = screenshot_bgr[y0:y1, x0:x1]
cv2.imwrite("roi_test.png", roi)
print("ROI gespeichert: roi_test.png")

if fish_bot._wurm_template is not None:
    ergebnis = cv2.matchTemplate(roi, fish_bot._wurm_template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(ergebnis)
    print(f"Max Match-Wert im ROI: {max_val:.3f} (Schwelle: {fish_bot.WURM_MATCH_SCHWELLE})")
    print(f"Beste Position: {max_loc}")
