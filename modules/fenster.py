# -*- coding: utf-8 -*-
"""fenster.py - Fenster-Erkennung fuer fenster-relative Aufnahmen (Windows).

Verwendet nur ctypes/user32 - keine Zusatzpakete. Auf Nicht-Windows liefern
die Funktionen None, sodass der Rest des Programms weiter funktioniert
(faellt dann auf absolute Koordinaten zurueck).

Rueckgabe-Format (Dict):
    {"titel": str, "hwnd": int, "x": int, "y": int, "w": int, "h": int}
x/y = linke obere Ecke des Fensters (Bildschirm-Koordinaten), w/h = Groesse.
"""

import sys

_WIN = sys.platform.startswith("win")

if _WIN:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    GA_ROOT = 2

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    # Signaturen setzen (wichtig fuer 64-bit-Korrektheit)
    user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.WindowFromPoint.argtypes = [POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    def _titel(hwnd):
        laenge = user32.GetWindowTextLengthW(hwnd)
        if laenge <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(laenge + 1)
        user32.GetWindowTextW(hwnd, buf, laenge + 1)
        return buf.value

    def _rect(hwnd):
        r = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)

    def _info(hwnd):
        rect = _rect(hwnd)
        if not rect:
            return None
        x, y, w, h = rect
        return {"titel": _titel(hwnd), "hwnd": int(hwnd),
                "x": x, "y": y, "w": w, "h": h}

    def fenster_unter_cursor():
        """Top-Level-Fenster unter dem aktuellen Mauszeiger."""
        pt = POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return None
        hwnd = user32.WindowFromPoint(pt)
        if not hwnd:
            return None
        root = user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        return _info(root)

    def fenster_finden(titel_teil):
        """Erstes sichtbares Fenster, dessen Titel titel_teil enthaelt."""
        if not titel_teil:
            return None
        gesucht = titel_teil.lower()
        treffer = []

        def _cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                t = _titel(hwnd)
                if t and gesucht in t.lower():
                    treffer.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_cb), 0)
        # bevorzugt exakter Titel, sonst erster Treffer
        for hwnd in treffer:
            if _titel(hwnd).lower() == gesucht:
                return _info(hwnd)
        return _info(treffer[0]) if treffer else None

    verfuegbar = True

else:  # Nicht-Windows: Fallback
    def fenster_unter_cursor():
        return None

    def fenster_finden(titel_teil):
        return None

    verfuegbar = False
