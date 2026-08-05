# main.py - Hauptprogramm (All-in-One)
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from config import lade_config, speichere_config
from ablauf_rekorder import AblaufRekorder, liste_ablauefe
from arduino_steuerung import ArduinoSteuerung

def zeige_menu():
    print("""
========================================
   VISION & INPUT AUTOMATION TOOL
========================================
 1) Ablauf aufzeichnen
 2) Ablauf abspielen
 3) Abläufe verwalten
 4) Arduino verbinden
 5) Einstellungen (COM-Port etc.)
 6) Hilfe
 0) Beenden
========================================
""")

def main():
    cfg = lade_config()
    arduino = ArduinoSteuerung(cfg["com_port"], cfg["baud_rate"])
    rekorder = AblaufRekorder(arduino)

    print("🎯 Vision & Input Automation Tool")
    print(f"   Arduino: {cfg['com_port']} (aktiv: {cfg['arduino_aktiv']})")

    while True:
        zeige_menu()
        wahl = input("Wahl: ").strip()

        if wahl == "1":
            if cfg["arduino_aktiv"] and not arduino.verbunden:
                arduino.verbinde()
            aufnahme = rekorder.starte_aufnahme()
            if aufnahme:
                name = input("Name für Ablauf: ").strip()
                if name:
                    rekorder.speichere_ablauf(name)

        elif wahl == "2":
            ablauefe = liste_ablauefe()
            if not ablauefe:
                print("❌ Keine Abläufe vorhanden.")
                continue
            print("Verfügbare Abläufe:", ", ".join(ablauefe))
            name = input("Ablaufname: ").strip()
            if name:
                try:
                    wdh = int(input("Wiederholungen (0=endlos): ").strip() or "1")
                except:
                    wdh = 1
                if cfg["arduino_aktiv"] and not arduino.verbunden:
                    arduino.verbinde()
                rekorder.spiele_ab(name, cfg, wdh)

        elif wahl == "3":
            ablauefe = liste_ablauefe()
            if not ablauefe:
                print("❌ Keine Abläufe vorhanden.")
            else:
                print("Gespeicherte Abläufe:")
                for a in ablauefe:
                    print(f"  - {a}")

        elif wahl == "4":
            arduino.verbinde()

        elif wahl == "5":
            print(f"\nAktueller COM-Port: {cfg['com_port']}")
            neu = input("Neuer COM-Port (Enter = behalten): ").strip()
            if neu:
                cfg["com_port"] = neu
                speichere_config(cfg)
                print(f"✅ COM-Port gesetzt: {neu}")
            print(f"Arduino aktiv: {cfg['arduino_aktiv']}")
            antwort = input("Aktivieren? (j/n): ").strip().lower()
            if antwort in ["j", "ja", "y", "yes"]:
                cfg["arduino_aktiv"] = True
            elif antwort in ["n", "nein", "no"]:
                cfg["arduino_aktiv"] = False
            speichere_config(cfg)
            print("✅ Einstellungen gespeichert.")

        elif wahl == "6":
            print("""
HILFE
=====
1) Ablauf aufzeichnen:
   - Wähle '1', dann klicke/taste im Spiel
   - Drücke F9 zum Stoppen
   - Gib einen Namen ein

2) Ablauf abspielen:
   - Wähle '2', gib den Namen ein
   - Wiederholungen: 0 = endlos, 1 = einmal, 5 = fünfmal

3) Arduino:
   - Verbinde den Pro Micro per USB
   - Finde den COM-Port im Geräte-Manager
   - Setze ihn unter '5) Einstellungen'
   - Ohne Arduino werden Software-Klicks verwendet

TIPP: Stelle zuerst den COM-Port ein (Menüpunkt 5)!
""")

        elif wahl == "0":
            print("👋 Auf Wiedersehen!")
            arduino.trenne()
            break

        else:
            print("❌ Ungültige Wahl.")

if __name__ == "__main__":
    main()
