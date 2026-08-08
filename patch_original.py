import io, os, re

PFAD = r"C:\Users\vm1\Desktop\VideoTool-src\fish_bot.py"
with io.open(PFAD, "r", encoding="utf-8") as f:
    code = f.read()

# --- 1) Neue Konstanten einfuegen (Original-Strategie) ---
code = code.replace(
    "ZYKLUS_PAUSE = 0.2  # Sekunden zwischen zwei Suchdurchlaeufen waehrend FISCHEN",
    "ZYKLUS_PAUSE = 0.2  # Sekunden zwischen zwei Suchdurchlaeufen waehrend FISCHEN\n"
    "WAIT_AFTER_CLICK = 1.0  # Original-Strategie: 1s Pause nach jedem Klick\n"
    "MAX_KLICK_PRO_POPUP = 3  # Original-Strategie: max. 3 Klicks pro Popup\n"
    "KREIS_FAKTOR = 0.85  # Original-Strategie: Fisch muss in 85% des Kreises sein (Fischmitte)"
)

# --- 2) im_ring -> fisch_im_kreis (Fisch MITTE im Kreis) ---
alt_ring = '''def im_ring(punkt, mittelpunkt, radius):
    """Prueft, ob 'punkt' innerhalb von 'radius + RING_HITBOX_PX' um 'mittelpunkt'
    liegt (beide (x, y)) - also ueberall von der Mitte bis zum Ringrand, plus eine
    kleine Hitbox von ein paar Pixeln ueber den Rand hinaus.
    """
    radius_toleriert = radius + RING_HITBOX_PX
    dx = punkt[0] - mittelpunkt[0]
    dy = punkt[1] - mittelpunkt[1]
    return (dx * dx + dy * dy) <= (radius_toleriert * radius_toleriert)'''

neu_ring = '''def fisch_im_kreis(punkt, mittelpunkt, radius):
    """Original-Strategie (DownD/MetinFishingCV): Prueft, ob 'punkt' (Fischmitte)
    innerhalb des Kreises liegt (KREIS_FAKTOR * radius, damit der Fisch wirklich
    im Kreis ist und nicht nur am Rand). Beide (x, y).
    """
    radius_toleriert = radius * KREIS_FAKTOR
    dx = punkt[0] - mittelpunkt[0]
    dy = punkt[1] - mittelpunkt[1]
    return (dx * dx + dy * dy) <= (radius_toleriert * radius_toleriert)'''

if alt_ring in code:
    code = code.replace(alt_ring, neu_ring)
    print("PATCH_OK - fisch_im_kreis eingefuegt")
else:
    print("PATCH_FEHLER - im_ring Basis-String nicht gefunden")
    raise SystemExit(1)

# --- 3) _fischen_tick umbauen: Rueckgabe (popup, letzte_fisch, klick_gesendet) ---
alt_tick = '''    popup = _popup_mit_haltezeit(_popup_gueltig(popup_finden(screenshot)))
    ziel = ziel_finden(screenshot)
    ring_treffer = bool(popup is not None and ziel is not None
                         and im_ring(ziel, (popup[0], popup[1]), popup[2]))
    distanz = (_distanz(ziel, (popup[0], popup[1]))
               if (popup is not None and ziel is not None) else None)
    fisch_speed = _fisch_geschwindigkeit(letzte_fisch, ziel, t_screenshot)
    neue_letzte_fisch = (ziel[0], ziel[1], t_screenshot) if ziel is not None else letzte_fisch

    _status_loggen(popup, ziel, ring_treffer)

    klick_gesendet = False
    latenz_ms = None
    if ring_treffer:
        ziel_x, ziel_y = ziel
        bildschirm_x = fenster["x"] + ziel_x
        bildschirm_y = fenster["y"] + ziel_y
        _logger.info("Ziel im Ring bei (%d, %d)", bildschirm_x, bildschirm_y)
        _logger.info("maus_zieht_zu=(%d, %d)", bildschirm_x, bildschirm_y)
        maus_bewegen(bildschirm_x, bildschirm_y, maus)
        klick_gesendet = True
        klick_erfolg = maus.klick_links()
        _logger.info("KLICK GESENDET: ziel=(%d, %d) erfolg=%s", bildschirm_x, bildschirm_y, klick_erfolg)
        # DIAGNOSE (Latenz-Logger, Fix 2): Zeit von Screenshot-Zeitpunkt bis
        # zur Rueckkehr von klick_links() - deckt Bildverarbeitung, SetCursorPos
        # und den seriellen Roundtrip zum Arduino (inkl. "CLICKED"-Warten) ab.
        latenz_ms = (time.time() - t_screenshot) * 1000
        if not klick_erfolg:
            _logger.warning("Klick fehlgeschlagen (keine Bestaetigung von der HID-Maus)")

    _csv_zeile_schreiben(fenster, popup, ziel, distanz, ring_treffer, klick_gesendet,
                          latenz_ms, fisch_speed)

    return popup, neue_letzte_fisch'''

neu_tick = '''    popup = _popup_mit_haltezeit(_popup_gueltig(popup_finden(screenshot)))
    ziel = ziel_finden(screenshot)
    kreis_treffer = bool(popup is not None and ziel is not None
                         and fisch_im_kreis(ziel, (popup[0], popup[1]), popup[2]))
    distanz = (_distanz(ziel, (popup[0], popup[1]))
               if (popup is not None and ziel is not None) else None)
    fisch_speed = _fisch_geschwindigkeit(letzte_fisch, ziel, t_screenshot)
    neue_letzte_fisch = (ziel[0], ziel[1], t_screenshot) if ziel is not None else letzte_fisch

    _status_loggen(popup, ziel, kreis_treffer)

    klick_gesendet = False
    latenz_ms = None
    if kreis_treffer:
        ziel_x, ziel_y = ziel
        bildschirm_x = fenster["x"] + ziel_x
        bildschirm_y = fenster["y"] + ziel_y
        _logger.info("Fisch im Kreis bei (%d, %d)", bildschirm_x, bildschirm_y)
        _logger.info("maus_zieht_zu=(%d, %d)", bildschirm_x, bildschirm_y)
        maus_bewegen(bildschirm_x, bildschirm_y, maus)
        klick_gesendet = True
        klick_erfolg = maus.klick_links()
        _logger.info("KLICK GESENDET: ziel=(%d, %d) erfolg=%s", bildschirm_x, bildschirm_y, klick_erfolg)
        latenz_ms = (time.time() - t_screenshot) * 1000
        if not klick_erfolg:
            _logger.warning("Klick fehlgeschlagen (keine Bestaetigung von der HID-Maus)")

    _csv_zeile_schreiben(fenster, popup, ziel, distanz, kreis_treffer, klick_gesendet,
                          latenz_ms, fisch_speed)

    return popup, neue_letzte_fisch, klick_gesendet'''

if alt_tick in code:
    code = code.replace(alt_tick, neu_tick)
    print("PATCH_OK - _fischen_tick umgebaut")
else:
    print("PATCH_FEHLER - _fischen_tick Basis-String nicht gefunden")
    raise SystemExit(1)

# --- 4) zustand_fischen umbauen: 1 Klick, WAIT_AFTER_CLICK, max 3 ---
alt_zustand = '''    popup_war_je_offen = False
    geschlossen_seit = None
    letzte_fisch = None  # (x, y, zeitpunkt) fuer _fisch_geschwindigkeit()

    while True:
        if _gestoppt():
            return ZUSTAND_GESTOPPT

        fenster = fenster_finden_geprueft()
        if fenster is None:
            time.sleep(ZYKLUS_PAUSE)
            continue

        popup, letzte_fisch = _fischen_tick(maus, fenster, letzte_fisch)

        if popup is not None:
            popup_war_je_offen = True
            geschlossen_seit = None
        elif popup_war_je_offen:
            jetzt = time.time()
            if geschlossen_seit is None:
                geschlossen_seit = jetzt
            elif jetzt - geschlossen_seit >= POPUP_SCHLIESS_DEBOUNCE:
                return ZUSTAND_WARTE_EINHOLEN

        time.sleep(ZYKLUS_PAUSE)'''

neu_zustand = '''    popup_war_je_offen = False
    geschlossen_seit = None
    letzte_fisch = None  # (x, y, zeitpunkt) fuer _fisch_geschwindigkeit()
    klicks_in_diesem_popup = 0

    while True:
        if _gestoppt():
            return ZUSTAND_GESTOPPT

        fenster = fenster_finden_geprueft()
        if fenster is None:
            time.sleep(ZYKLUS_PAUSE)
            continue

        popup, letzte_fisch, klick_gesendet = _fischen_tick(maus, fenster, letzte_fisch)

        if popup is not None:
            popup_war_je_offen = True
            geschlossen_seit = None
            if klick_gesendet:
                klicks_in_diesem_popup += 1
                _logger.info("Klick %d/%d in diesem Popup", klicks_in_diesem_popup, MAX_KLICK_PRO_POPUP)
                # Original-Strategie: nach jedem Klick 1s warten (WAIT_AFTER_CLICK)
                warte_mit_bonus(WAIT_AFTER_CLICK)
                if _gestoppt():
                    return ZUSTAND_GESTOPPT
            elif klicks_in_diesem_popup >= MAX_KLICK_PRO_POPUP:
                # Max. Klicks erreicht - nur noch auf Popup-Schliessen warten
                time.sleep(ZYKLUS_PAUSE)
                continue
        elif popup_war_je_offen:
            jetzt = time.time()
            if geschlossen_seit is None:
                geschlossen_seit = jetzt
            elif jetzt - geschlossen_seit >= POPUP_SCHLIESS_DEBOUNCE:
                return ZUSTAND_WARTE_EINHOLEN

        time.sleep(ZYKLUS_PAUSE)'''

if alt_zustand in code:
    code = code.replace(alt_zustand, neu_zustand)
    print("PATCH_OK - zustand_fischen umgebaut")
else:
    print("PATCH_FEHLER - zustand_fischen Basis-String nicht gefunden")
    raise SystemExit(1)

with io.open(PFAD, "w", encoding="utf-8") as f:
    f.write(code)
print("PATCH_ABGESCHLOSSEN")
