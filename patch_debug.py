# -*- coding: utf-8 -*-
import io

pfad = 'command_center.py'
src = io.open(pfad, encoding='utf-8').read()

alt = 'def _rec_start(self):\n        if BotStatus.aufnahme_laeuft:\n            return'
neu = 'def _rec_start(self):\n        self._log_fish("DEBUG: _rec_start aufgerufen")\n        if BotStatus.aufnahme_laeuft:\n            self._log_fish("DEBUG: laeuft schon, return")\n            return'
if alt in src:
    src = src.replace(alt, neu)
    io.open(pfad, 'w', encoding='utf-8').write(src)
    print('PATCH_OK')
else:
    print('ALT_TEXT_NICHT_GEFUNDEN')
