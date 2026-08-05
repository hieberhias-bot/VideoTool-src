# config.py - Zentrale Einstellungen
import json, os

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "tool_config.json")

DEFAULT_CONFIG = {
    # Arduino
    "com_port": "COM3",              # <- hier COM-Port einstellen
    "baud_rate": 115200,
    "arduino_aktiv": True,

    # Humanisierung - Zeit
    "zeit_abstand_min": 0.1,         # min. Sekunden zwischen Klicks
    "zeit_abstand_max": 0.5,         # max. Sekunden zwischen Klicks
    "lange_pause_wahrscheinlichkeit": 0.15,  # 15% Chance auf lange Pause
    "lange_pause_min": 10,           # min. Sekunden lange Pause
    "lange_pause_max": 30,           # max. Sekunden lange Pause

    # Humanisierung - Pixel (Klick-Ungenauigkeit)
    "pixel_ungenauigkeit_min": 2,    # min. Pixel Abweichung
    "pixel_ungenauigkeit_max": 5,    # max. Pixel Abweichung

    # Ziel-Erkennung
    "ziel_farbe": None,              # z.B. [200, 50, 50] (BGR)
    "ziel_toleranz": 30,             # Farbtoleranz
    "ziel_region": None,             # z.B. [0, 0, 1920, 1080]

    # Multi-Pixel-Trigger
    "trigger_pixel": [],             # Liste von {x, y, farbe} relativ zum Fenster
    "trigger_toleranz": 25,          # Farbtoleranz pro Kanal
    "trigger_aktiv": False,          # Trigger-System an/aus
}

def lade_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            cfg = json.load(f)
        # Defaults ergänzen
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    return dict(DEFAULT_CONFIG)

def speichere_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8-sig") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)





class ToolConfig:
    CONFIG_FILE = CONFIG_FILE
    DEFAULT_CONFIG = DEFAULT_CONFIG

    def __init__(self):
        self.config = lade_config()

    def get(self, key, default=None):
        return self.config.get(key, default)
