import sys, os
sys.path.insert(0, r"C:\Users\vm1\Desktop\VideoTool-src")
os.chdir(r"C:\Users\vm1\Desktop\VideoTool-src")
import fish_bot
from modules.fenster import fenster_finden
from hid_maus import HIDMaus

fenster = fenster_finden("METIN2")
print("Fenster:", fenster)

# Screenshot wie im Bot
from PIL import ImageGrab
screenshot = ImageGrab.grab(bbox=(fenster["x"], fenster["y"], fenster["x"]+fenster["w"], fenster["y"]+fenster["h"]))
import numpy as np
screenshot_bgr = np.array(screenshot.convert("RGB"))[:, :, ::-1]

stapel = fish_bot.wurm_stapel_finden(screenshot_bgr)
print("Gefundene Wurm-Stapel:", stapel)

if stapel:
    ziel_x, ziel_y = stapel[0]
    th, tw = fish_bot._wurm_template.shape[:2]
    hitbox_w = tw + 2 * fish_bot.WURM_HITBOX_ERWEITERUNG
    hitbox_h = th + 2 * fish_bot.WURM_HITBOX_ERWEITERUNG
    print(f"Hitbox: {hitbox_w}x{hitbox_h}px um ({ziel_x}, {ziel_y})")
    print(f"Klickbereich: x {ziel_x-5}..{ziel_x+5}, y {ziel_y-5}..{ziel_y+5}")
