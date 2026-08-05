#!/usr/bin/env python3
"""fenster_utils.py - Fenster-Erkennung & Koordinaten-Umrechnung fuer Metin2"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

def fenster_holen(titel_teil):
    ergebnis = []
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            laenge = user32.GetWindowTextLengthW(hwnd)
            if laenge > 0:
                buf = ctypes.create_unicode_buffer(laenge + 1)
                user32.GetWindowTextW(hwnd, buf, laenge + 1)
                if titel_teil.lower() in buf.value.lower():
                    ergebnis.append(hwnd)
        return True
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return ergebnis[0] if ergebnis else None

def fenster_rect(hwnd):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    breite = rect.right - rect.left
    hoehe = rect.bottom - rect.top
    return rect.left, rect.top, breite, hoehe

def fenster_info(titel_teil="Metin2"):
    hwnd = fenster_holen(titel_teil)
    if not hwnd:
        return None
    x, y, breite, hoehe = fenster_rect(hwnd)
    return {"hwnd": hwnd, "x": x, "y": y, "breite": breite, "hoehe": hoehe}

def absolut_zu_relativ(x, y, fenster):
    if not fenster:
        return x, y
    return x - fenster["x"], y - fenster["y"]

def relativ_zu_absolut(rx, ry, fenster):
    if not fenster:
        return rx, ry
    return rx + fenster["x"], ry + fenster["y"]
