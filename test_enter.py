import time
import win32gui

from hid_maus import HIDMaus


def main():
    hwnd = win32gui.FindWindow(None, "METIN2")
    if hwnd:
        print(f"Fenster gefunden: hwnd={hwnd}")
        win32gui.SetForegroundWindow(hwnd)
        print("Fenster in den Vordergrund geholt")
    else:
        print("Fenster 'METIN2' nicht gefunden - Test laeuft trotzdem weiter")

    time.sleep(0.5)

    m = HIDMaus('COM6')
    verbunden = m.verbinden()
    print(f"Verbindung: {verbunden}")

    if not verbunden:
        print("Abbruch: keine Verbindung zum Arduino")
        return

    ergebnis1 = m.taste_druecken('ENTER')
    print(f"Enter 1: {ergebnis1}")

    time.sleep(0.5)

    ergebnis2 = m.taste_druecken('ENTER')
    print(f"Enter 2: {ergebnis2}")

    m.schliessen()


if __name__ == "__main__":
    main()
