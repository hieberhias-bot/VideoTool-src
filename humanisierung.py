# humanisierung.py - Menschliche Ungenauigkeit
import random, time

def zufalls_zeit(cfg):
    """Zufällige Wartezeit zwischen Aktionen."""
    return random.uniform(cfg["zeit_abstand_min"], cfg["zeit_abstand_max"])

def vielleicht_lange_pause(cfg):
    """Mit Wahrscheinlichkeit eine lange Pause machen."""
    if random.random() < cfg["lange_pause_wahrscheinlichkeit"]:
        dauer = random.uniform(cfg["lange_pause_min"], cfg["lange_pause_max"])
        print(f"  ⏸  Lange Pause: {dauer:.1f}s")
        time.sleep(dauer)
        return True
    return False

def pixel_abweichung(cfg):
    """Zufällige Pixel-Abweichung für Klicks."""
    abw = random.randint(cfg["pixel_ungenauigkeit_min"], cfg["pixel_ungenauigkeit_max"])
    dx = random.choice([-1, 1]) * random.randint(0, abw)
    dy = random.choice([-1, 1]) * random.randint(0, abw)
    return dx, dy

def warte_human(cfg):
    """Kurze Wartezeit + evtl. lange Pause."""
    time.sleep(zufalls_zeit(cfg))
    vielleicht_lange_pause(cfg)
