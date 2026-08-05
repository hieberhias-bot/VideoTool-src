import io

# 1) BOM entfernen + Datei neu schreiben
with io.open("command_center.py", "r", encoding="utf-8-sig") as f:
    src = f.read()

# 2) Verwaiste Ueberreste der alten Methode entfernen (on_click + Listener)
#    Diese stehen jetzt zwischen der neuen Methode und der naechsten def
start = src.index("        self._fenster_erfasst({\"titel\": such, **info})")
ende = src.index("    def ", start + 10)
rest = src[start:ende]

# Finde das Ende der neuen Methode (die Leerzeile vor der naechsten def)
# Neue Methode endet mit dem self._fenster_erfasst Aufruf
neu_ende = src.index("        self._fenster_erfasst({\"titel\": such, **info})")
neu_ende += len("        self._fenster_erfasst({\"titel\": such, **info})")

# Alles zwischen dem Ende der neuen Methode und der naechsten def ist Muell
muell_start = neu_ende
muell_ende = src.index("    def ", muell_start + 10)
muell = src[muell_start:muell_ende]

# Entferne den Muell
src = src[:muell_start] + "\n\n" + src[muell_ende:]

# 3) Ohne BOM speichern
with io.open("command_center.py", "w", encoding="utf-8", newline="\n") as f:
    f.write(src)

print("CLEANUP_OK")
