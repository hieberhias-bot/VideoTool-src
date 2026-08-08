import re

with open('fish_bot.py', 'r', encoding='utf-8') as f:
    inhalt = f.read()

# 1. Neue Funktion einfügen (vor der ersten Verwendung)
funktion = '''
def klickpunkt_auf_linie(A, B, ABSTAND=15):
    """Punkt C auf der Linie A->B, ABSTAND px hinter B."""
    dx = B[0] - A[0]
    dy = B[1] - A[1]
    laenge = (dx*dx + dy*dy) ** 0.5
    if laenge < 1:
        return B
    einheit_x = dx / laenge
    einheit_y = dy / laenge
    return (B[0] + einheit_x * ABSTAND, B[1] + einheit_y * ABSTAND)
'''

# Funktion vor 'def _fischen_tick' einfügen
if 'klickpunkt_auf_linie' not in inhalt:
    inhalt = inhalt.replace('def _fischen_tick', funktion + '\ndef _fischen_tick', 1)

with open('fish_bot.py', 'w', encoding='utf-8') as f:
    f.write(inhalt)

print("PATCH_OK")
