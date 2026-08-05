# -*- coding: utf-8 -*-
src = open("command_center.py", encoding="utf-8").read()
alt = "if self.recording:"
neu = "if self._rec_listener is not None:"
if alt in src:
    src = src.replace(alt, neu, 1)
    open("command_center.py", "w", encoding="utf-8", newline="\n").write(src)
    print("PATCH_OK")
else:
    print("NICHT_GEFUNDEN")
