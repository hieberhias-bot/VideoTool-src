import sys, os
sys.path.insert(0, r"C:\Users\vm1\Desktop\VideoTool-src")
os.chdir(r"C:\Users\vm1\Desktop\VideoTool-src")
import fish_bot
import cv2
from PIL import ImageGrab
import numpy as np
from modules.fenster import fenster_finden
from hid_maus import HIDMaus

fenster = fenster_finden("METIN2")
print("Fenster:", fenster)

screenshot = ImageGrab.grab(bbox=(fenster["x"], fenster["y"], fenster["x"]+fenster["w"], fenster["y"]+fenster["h"]))
screenshot_bgr = np.array(screenshot.convert("RGB"))[:, :, ::-1]

stapel = fish_bot.wurm_stapel_finden(screenshot_bgr)
print("Gefundene Wurm-Stapel (Fenster-Koordinaten):", stapel)

if stapel:
    ziel_x, ziel_y = stapel[0]
    # In Bildschirm-Koordinaten umrechnen
    bildschirm_x = fenster["x"] + ziel_x
    bildschirm_y = fenster["y"] + ziel_y
    print(f"Ziel auf Bildschirm: ({bildschirm_x}, {bildschirm_y})")
    
    m = HIDMaus()
    m.verbinden()
    print("Verbunden:", m.verbunden)
    m.maus_ziehen(bildschirm_x, bildschirm_y)
    import time
    time.sleep(0.3)
    m.klick_links()
    print("Klick gesendet!")
else:
    print("Keine Wurm-Stapel gefunden - Inventar offen?")
