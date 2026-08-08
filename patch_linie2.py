# -*- coding: utf-8 -*-
with open('fish_bot.py', 'r', encoding='utf-8') as f:
    inhalt = f.read()

# 1. Neue Funktion einfügen (vor klickpunkt_auf_linie)
funktion = '''
def fisch_linie_anvisieren(glaetter, abstand=15):
    """Zielt auf Punkt C auf der Linie A->B, ABSTAND px hinter B.
    A, B = die letzten beiden geglaetteten Fischpositionen.
    Ohne 2 Positionen (Stillstand/Start) -> aktuelle geglaettete Position."""
    if glaetter is None:
        return None
    hist = glaetter._geglaettete_historie
    if len(hist) < 2:
        return glaetter.position()
    A = (hist[-2][0], hist[-2][1])
    B = (hist[-1][0], hist[-1][1])
    return klickpunkt_auf_linie(A, B, abstand)

'''

if 'fisch_linie_anvisieren' not in inhalt:
    inhalt = inhalt.replace('def klickpunkt_auf_linie', funktion + 'def klickpunkt_auf_linie', 1)

# 2. Aufrufstelle ersetzen
alt = 'ring_ziel = fisch_spitze_anvisieren(glaetter)'
neu = 'ring_ziel = fisch_linie_anvisieren(glaetter)'
if alt in inhalt:
    inhalt = inhalt.replace(alt, neu, 1)
    print("AUFRUF_ERSETZT")
else:
    print("AUFRUF_NICHT_GEFUNDEN")

with open('fish_bot.py', 'w', encoding='utf-8') as f:
    f.write(inhalt)

print("PATCH_OK")
