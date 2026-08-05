# trigger.py - Multi-Pixel-Trigger (Fensterwahl + Pixel sammeln + Beobachten)
import time, random
from pynput import mouse, keyboard
import config

class TriggerSystem:
    def __init__(self):
        self.fenster_region = None   # [x, y, w, h] des gewählten Fensters
        self.pixel = []              # [{x, y, farbe}] relativ zum Fenster
        self.beobachtet = False
        self.trigger_erfuellt = False

    # ---------- FENSTER WÄHLEN ----------
    def waehle_fenster(self):
        """Klick-Modus: Benutzer klickt in das Fenster."""
        print("Klicke in das Fenster, das beobachtet werden soll (ESC = abbrechen)...")
        self.fenster_region = None

        def on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.left:
                self.fenster_region = [x, y, 0, 0]
                print(f"Fenster gewaehlt bei ({x}, {y})")
                return False
            return True

        with mouse.Listener(on_click=on_click) as listener:
            listener.join()
        return self.fenster_region

    # ---------- PIXEL SAMMELN (Klick-Modus) ----------
    def sammle_pixel(self):
        """Klick-Modus: Benutzer klickt auf Trigger-Pixel. ESC = fertig."""
        self.pixel = []
        print("Klicke auf die Trigger-Pixel (mehrere). ESC = fertig.")
        print("Alle Pixel muessen ihre Farbe treffen, damit die Aufnahme startet.")

        def on_click(x, y, button, pressed):
            if pressed and button == mouse.Button.left:
                farbe = self._lies_farbe(x, y)
                rx = x - self.fenster_region[0]
                ry = y - self.fenster_region[1]
                self.pixel.append({"x": rx, "y": ry, "farbe": farbe})
                print(f"Pixel {len(self.pixel)}: ({rx}, {ry}) Farbe {farbe}")

        def on_press(taste):
            if taste == keyboard.Key.esc:
                print(f"{len(self.pixel)} Pixel gespeichert.")
                return False

        with mouse.Listener(on_click=on_click) as m_listener:
            with keyboard.Listener(on_press=on_press) as k_listener:
                m_listener.join()
                k_listener.join()

        cfg = config.lade_config()
        cfg["trigger_pixel"] = self.pixel
        cfg["trigger_aktiv"] = True
        config.speichere_config(cfg)
        return self.pixel

    # ---------- BEOBACHTEN ----------
    def beobachte(self):
        """Scannt das Fenster, prueft ob ALLE Pixel treffen."""
        if not self.fenster_region or not self.pixel:
            print("Kein Fenster oder keine Pixel definiert.")
            return False

        import pyautogui
        cfg = config.lade_config()
        toleranz = cfg.get("trigger_toleranz", 25)
        fenster_x, fenster_y = self.fenster_region[0], self.fenster_region[1]

        for p in self.pixel:
            abs_x = fenster_x + p["x"]
            abs_y = fenster_y + p["y"]
            aktuell = pyautogui.pixel(abs_x, abs_y)
            ziel = tuple(p["farbe"])
            if not self._farben_passend(aktuell, ziel, toleranz):
                return False
        return True

    # ---------- WARTEN AUF TRIGGER ----------
    def warte_auf_trigger(self, callback=None):
        """Wartet, bis alle Pixel treffen. Dann startet die Aufnahme."""
        print("Beobachte Fenster auf Trigger...")
        self.trigger_erfuellt = False
        while not self.trigger_erfuellt:
            if self.beobachte():
                print("TRIGGER ERFUELLT! Starte Aufnahme.")
                self.trigger_erfuellt = True
                if callback:
                    callback()
                return True
            time.sleep(0.1)

    # ---------- HELFER ----------
    def _lies_farbe(self, x, y):
        import pyautogui
        return list(pyautogui.pixel(x, y))

    def _farben_passend(self, aktuell, ziel, toleranz):
        return all(abs(a - z) <= toleranz for a, z in zip(aktuell, ziel))
