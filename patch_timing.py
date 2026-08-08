import re
s = open('fish_bot.py', encoding='utf-8').read()
# Nach maus_bewegen_abs eine kurze Wartezeit vor dem Klick einfügen
old = "maus_bewegen_abs(ziel_x, ziel_y)"
new = "maus_bewegen_abs(ziel_x, ziel_y)\n        time.sleep(0.08)  # warten bis Maus physisch angekommen"
if old in s:
    s = s.replace(old, new)
    open('fish_bot.py', 'w', encoding='utf-8').write(s)
    print('PATCH_OK')
else:
    print('MUSTER NICHT GEFUNDEN')
