#!/usr/bin/env python3
"""test_fisch_glaettung.py - Testet FischGlaetter aus fish_bot.py mit
simulierten verrauschten Fisch-Positionen (den echten Werten aus
fish_daten.csv nachempfunden, siehe analyse_fisch.py: ~44.6px
durchschnittlicher Sprung, 66.7% der Spruenge >20px) und zeigt, wie stark die
Glaettung das Rauschen gegenueber den Rohwerten reduziert.
"""

import math

from fish_bot import FischGlaetter

# Verrauschte Testpositionen: eine "wahre" sanfte Fischbewegung (Kreisbahn)
# plus zufaelliges Rauschen in aehnlicher Groessenordnung wie in
# fish_daten.csv beobachtet (Spruenge ueberwiegend 20-100px).
import random

random.seed(42)


def wahre_bahn_kreis(n, mitte=(280, 220), radius=60, schritt_s=0.28):
    """Szenario A: durchgehende, recht schnelle Kreisbewegung - ein
    Belastungstest fuer die Glaettung (echte Bewegung fast so schnell wie
    das Rauschen selbst)."""
    punkte = []
    for i in range(n):
        winkel = i * 0.35
        x = mitte[0] + radius * math.cos(winkel)
        y = mitte[1] + radius * math.sin(winkel)
        punkte.append((x, y, i * schritt_s))
    return punkte


def wahre_bahn_realistisch(n, start=(280, 220), schritt_s=0.28):
    """Szenario B: ueberwiegend stillstehende/langsam driftende Position mit
    gelegentlichen kleinen Spruengen - naeher an den echten fish_daten.csv-
    Werten (viele 0 px/s-Phasen, dazwischen kurze Bewegungsschuebe), das ist
    der eigentliche Zielfall fuer die Glaettung."""
    x, y = start
    punkte = []
    for i in range(n):
        if random.random() < 0.25:
            x += random.uniform(-15, 15)
            y += random.uniform(-15, 15)
        punkte.append((x, y, i * schritt_s))
    return punkte


def verrauschen(punkte, sigma=35, ausreisser_chance=0.15, ausreisser_groesse=150):
    """Fuegt Gauss-Rauschen hinzu, gelegentlich einen groben Ausreisser
    (False-Positive der Bilderkennung, z.B. Hintergrundtextur)."""
    verrauscht = []
    for x, y, t in punkte:
        if random.random() < ausreisser_chance:
            nx = x + random.uniform(-ausreisser_groesse, ausreisser_groesse)
            ny = y + random.uniform(-ausreisser_groesse, ausreisser_groesse)
        else:
            nx = x + random.gauss(0, sigma)
            ny = y + random.gauss(0, sigma)
        verrauscht.append((nx, ny, t))
    return verrauscht


def distanz(p1, p2):
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


def mittel(werte):
    return sum(werte) / len(werte)


def szenario_auswerten(name, wahr, roh, ausfuehrlich=True):
    glaetter = FischGlaetter()

    fehler_roh, fehler_geglaettet = [], []
    spruenge_roh, spruenge_geglaettet = [], []
    letzte_roh = letzte_geglaettet = None

    print(f"\n=== Szenario: {name} ===")
    if ausfuehrlich:
        print(f"{'t':>5} {'wahr_x':>8} {'wahr_y':>8}  {'roh_x':>8} {'roh_y':>8}  "
              f"{'gegl_x':>8} {'gegl_y':>8}  {'err_roh':>8} {'err_gegl':>8}")

    for (wx, wy, t), (rx, ry, _) in zip(wahr, roh):
        gx, gy = glaetter.position(rx, ry)

        e_roh, e_gegl = distanz((rx, ry), (wx, wy)), distanz((gx, gy), (wx, wy))
        fehler_roh.append(e_roh)
        fehler_geglaettet.append(e_gegl)

        if letzte_roh is not None:
            spruenge_roh.append(distanz((rx, ry), letzte_roh))
            spruenge_geglaettet.append(distanz((gx, gy), letzte_geglaettet))
        letzte_roh, letzte_geglaettet = (rx, ry), (gx, gy)

        if ausfuehrlich:
            print(f"{t:5.2f} {wx:8.1f} {wy:8.1f}  {rx:8.1f} {ry:8.1f}  "
                  f"{gx:8.1f} {gy:8.1f}  {e_roh:8.1f} {e_gegl:8.1f}")

    print(f"Durchschnittlicher Sprung ROH:        {mittel(spruenge_roh):6.1f}px")
    print(f"Durchschnittlicher Sprung GEGLAETTET: {mittel(spruenge_geglaettet):6.1f}px  "
          f"(Reduktion {100 * (1 - mittel(spruenge_geglaettet) / mittel(spruenge_roh)):5.1f}%)")
    print(f"Fehler zur wahren Position ROH:        {mittel(fehler_roh):6.1f}px")
    print(f"Fehler zur wahren Position GEGLAETTET: {mittel(fehler_geglaettet):6.1f}px")

    return mittel(spruenge_roh), mittel(spruenge_geglaettet), mittel(fehler_roh), mittel(fehler_geglaettet)


def main():
    n = 40

    # Szenario A: durchgehende schnelle Kreisbewegung (Belastungstest).
    sa_sprung_roh, sa_sprung_gegl, sa_fehler_roh, sa_fehler_gegl = szenario_auswerten(
        "A - schnelle Kreisbewegung (Belastungstest)",
        wahre_bahn_kreis(n), verrauschen(wahre_bahn_kreis(n)))

    # Szenario B: ueberwiegend stillstehend/langsam driftend (realistischer
    # Zielfall, naeher an fish_daten.csv).
    wahr_b = wahre_bahn_realistisch(n)
    sb_sprung_roh, sb_sprung_gegl, sb_fehler_roh, sb_fehler_gegl = szenario_auswerten(
        "B - ueberwiegend ruhig, gelegentliche Spruenge (realistisch)",
        wahr_b, verrauschen(wahr_b))

    print("\n--- Gesamtfazit ---")
    print(f"Sprunggroesse (Jitter) wird in BEIDEN Szenarien stark reduziert: "
          f"A {sa_sprung_roh:.1f}->{sa_sprung_gegl:.1f}px, "
          f"B {sb_sprung_roh:.1f}->{sb_sprung_gegl:.1f}px.")
    print(f"Genauigkeit zur wahren Position: "
          f"A {sa_fehler_roh:.1f}->{sa_fehler_gegl:.1f}px "
          f"({'besser' if sa_fehler_gegl < sa_fehler_roh else 'SCHLECHTER'}), "
          f"B {sb_fehler_roh:.1f}->{sb_fehler_gegl:.1f}px "
          f"({'besser' if sb_fehler_gegl < sb_fehler_roh else 'SCHLECHTER'}).")

    assert sa_sprung_gegl < sa_sprung_roh and sb_sprung_gegl < sb_sprung_roh, \
        "Glaettung sollte die Sprunggroesse in beiden Szenarien reduzieren!"


if __name__ == "__main__":
    main()
