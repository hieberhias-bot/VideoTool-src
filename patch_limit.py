import io, os

PFAD = r"C:\Users\vm1\Desktop\VideoTool-src\fish_bot.py"
with io.open(PFAD, "r", encoding="utf-8") as f:
    code = f.read()

alt = '''        popup, letzte_fisch, klick_gesendet = _fischen_tick(maus, fenster, letzte_fisch)

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
        elif popup_war_je_offen:'''

neu = '''        # Original-Strategie: nach MAX_KLICK_PRO_POPUP Klicks nicht mehr klicken,
        # nur noch auf das Popup-Schliessen warten.
        if klicks_in_diesem_popup >= MAX_KLICK_PRO_POPUP:
            popup, letzte_fisch, _ = _fischen_tick(maus, fenster, letzte_fisch, max_klicks=False)
            if popup is not None:
                popup_war_je_offen = True
                geschlossen_seit = None
            elif popup_war_je_offen:
                jetzt = time.time()
                if geschlossen_seit is None:
                    geschlossen_seit = jetzt
                elif jetzt - geschlossen_seit >= POPUP_SCHLIESS_DEBOUNCE:
                    return ZUSTAND_WARTE_EINHOLEN
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
        elif popup_war_je_offen:'''

if alt in code:
    code = code.replace(alt, neu)
    print("PATCH_OK - zustand_fischen Limit-Logik eingebaut")
else:
    print("PATCH_FEHLER - Basis-String nicht gefunden")
    raise SystemExit(1)

# _fischen_tick braucht jetzt einen max_klicks-Parameter
alt_sig = "def _fischen_tick(maus, fenster, letzte_fisch=None):"
neu_sig = "def _fischen_tick(maus, fenster, letzte_fisch=None, max_klicks=True):"
if alt_sig in code:
    code = code.replace(alt_sig, neu_sig)
    print("PATCH_OK - _fischen_tick Signatur erweitert")
else:
    print("PATCH_FEHLER - Signatur nicht gefunden")
    raise SystemExit(1)

# Klick nur senden, wenn max_klicks erlaubt
alt_klick = "    if kreis_treffer:"
neu_klick = "    if kreis_treffer and max_klicks:"
if alt_klick in code:
    code = code.replace(alt_klick, neu_klick)
    print("PATCH_OK - Klick-Bedingung an max_klicks gekoppelt")
else:
    print("PATCH_FEHLER - Klick-Bedingung nicht gefunden")
    raise SystemExit(1)

with io.open(PFAD, "w", encoding="utf-8") as f:
    f.write(code)
print("PATCH_ABGESCHLOSSEN")
