# ablauf_rekorder.py - Aufzeichnung und Abspielen
import json, os, time, random
from pynput import mouse, keyboard
import humanisierung

ABLAEUFE_ORDNER = os.path.join(os.path.dirname(__file__), "ablauefe")

class AblaufRekorder:
    def __init__(self, arduino=None):
        self.arduino = arduino
        self.aufnahme = []
        self.aufnimmt = False
        self.stopp_taste = keyboard.Key.f9  # F9 zum Stoppen

    # ---------- AUFZEICHNUNG ----------
    def starte_aufnahme(self, auf_trigger_warten=False, trigger=None):
        if auf_trigger_warten and trigger:
            trigger.warte_auf_trigger()
        self.aufnahme = []
        self.aufnimmt = True
        self.startzeit = time.time()
        print(f"🎥 Aufnahme gestartet. Drücke F9 zum Stoppen.")

        def on_click(x, y, button, pressed):
            if not self.aufnimmt:
                return False
            if pressed:
                zeit = time.time() - self.startzeit
                self.aufnahme.append({
                    "typ": "klick",
                    "x": x, "y": y,
                    "taste": str(button),
                    "zeit": round(zeit, 3)
                })
                print(f"  📍 Klick: ({x}, {y}) {button}")

        def on_press(taste):
            if taste == self.stopp_taste:
                self.aufnimmt = False
                print("⏹  Aufnahme gestoppt.")
                return False
            zeit = time.time() - self.startzeit
            try:
                self.aufnahme.append({
                    "typ": "taste",
                    "taste": str(taste.char),
                    "zeit": round(zeit, 3)
                })
            except:
                pass

        with mouse.Listener(on_click=on_click) as m_listener:
            with keyboard.Listener(on_press=on_press) as k_listener:
                m_listener.join()
                k_listener.join()

        return self.aufnahme

    def speichere_ablauf(self, name):
        if not os.path.exists(ABLAEUFE_ORDNER):
            os.makedirs(ABLAEUFE_ORDNER)
        datei = os.path.join(ABLAEUFE_ORDNER, f"{name}.json")
        with open(datei, "w", encoding="utf-8") as f:
            json.dump(self.aufnahme, f, indent=2)
        print(f"💾 Ablauf gespeichert: {datei}")
        return datei

    # ---------- ABSPIELEN ----------
    def lade_ablauf(self, name):
        datei = os.path.join(ABLAEUFE_ORDNER, f"{name}.json")
        if not os.path.exists(datei):
            print(f"❌ Ablauf nicht gefunden: {datei}")
            return None
        with open(datei, "r", encoding="utf-8") as f:
            return json.load(f)

    def spiele_ab(self, name, cfg, wiederholungen=1):
        ablauf = self.lade_ablauf(name)
        if not ablauf:
            return

        print(f"▶️  Spiele '{name}' ab ({wiederholungen}x)...")
        for runde in range(wiederholungen):
            print(f"  --- Runde {runde+1}/{wiederholungen} ---")
            letzte_zeit = 0
            for schritt in ablauf:
                # Zeit bis zum nächsten Schritt
                delta = schritt["zeit"] - letzte_zeit
                letzte_zeit = schritt["zeit"]
                if delta > 0:
                    time.sleep(min(delta, 2))  # max 2s warten, Rest humanisiert

                humanisierung.warte_human(cfg)

                if schritt["typ"] == "klick":
                    # Pixel-Ungenauigkeit
                    dx, dy = humanisierung.pixel_abweichung(cfg)
                    x = schritt["x"] + dx
                    y = schritt["y"] + dy

                    if self.arduino and self.arduino.verbunden:
                        self.arduino.klicke_abs(x, y)
                    else:
                        # Fallback: pyautogui
                        import pyautogui
                        pyautogui.click(x, y)
                    print(f"  🖱️  Klick: ({x}, {y})")

                elif schritt["typ"] == "taste":
                    print(f"  ⌨️  Taste: {schritt['taste']}")

        print("✅ Abspielen fertig.")

def liste_ablauefe():
    if not os.path.exists(ABLAEUFE_ORDNER):
        return []
    return [f.replace(".json", "") for f in os.listdir(ABLAEUFE_ORDNER) if f.endswith(".json")]

