#!/usr/bin/env python3
"""modules/fenster.py - Fenster-Erkennung fuer fenster-relative Aufnahmen"""

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

verfuegbar = True

# Systemfenster/Overlays, die nie als Zielfenster dienen sollen
_AUSSCHLUSS = ("microsoft text input", "program manager", "shell_traywnd",
               "default ime", "windows input experience", "task switching",
               "start", "search", "notification")

def _ist_ignorieren(titel):
    t = titel.lower()
    return not titel.strip() or any(s in t for s in _AUSSCHLUSS)

def _alle_fenster():
    fenster = []
    def callback(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            laenge = user32.GetWindowTextLengthW(hwnd)
            titel = ""
            if laenge > 0:
                buf = ctypes.create_unicode_buffer(laenge + 1)
                user32.GetWindowTextW(hwnd, buf, laenge + 1)
                titel = buf.value
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w > 0 and h > 0 and not _ist_ignorieren(titel):
                fenster.append((hwnd, titel, rect.left, rect.top, w, h))
        return True
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return fenster

def fenster_holen(titel_teil):
    for hwnd, titel, x, y, w, h in _alle_fenster():
        if titel_teil.lower() in titel.lower():
            return hwnd
    return None

def fenster_finden(titel_teil):
    hwnd = fenster_holen(titel_teil)
    if not hwnd:
        return None
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    breite = rect.right - rect.left
    hoehe = rect.bottom - rect.top
    return {"x": rect.left, "y": rect.top, "w": breite, "h": hoehe}

def fenster_unter_cursor():
    """Ermittelt das groesste NICHT-System-Fenster unter der aktuellen Mausposition."""
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    mx, my = point.x, point.y

    kandidaten = []
    for hwnd, titel, x, y, w, h in _alle_fenster():
        if x <= mx < x + w and y <= my < y + h:
            kandidaten.append((hwnd, titel, x, y, w, h))

    if not kandidaten:
        return None

    # Groesstes Fenster unter dem Cursor waehlen (meist das Spielfenster)
    kandidaten.sort(key=lambda k: k[4] * k[5], reverse=True)
    hwnd, titel, x, y, w, h = kandidaten[0]
    return {"x": x, "y": y, "w": w, "h": h, "titel": titel}
