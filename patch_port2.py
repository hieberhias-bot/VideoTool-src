import re
s = open('hid_maus.py', encoding='utf-8').read()

# 1. __init__ so aendern, dass port=None automatisch gefunden wird
s = s.replace(
    "self.port = port",
    "self.port = port or _port_auto_finden()"
)

# 2. verbinden() so aendern, dass bei fehlendem Port neu gesucht wird
old = '''def verbinden(self):
        """Öffnet die serielle Verbindung zum Arduino."""
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)'''
new = '''def verbinden(self):
        """Öffnet die serielle Verbindung zum Arduino."""
        try:
            if not self.port:
                self.port = _port_auto_finden()
                if not self.port:
                    print("[HIDMaus] Kein Arduino Micro gefunden (COM-Port).")
                    self.verbunden = False
                    return False
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)'''
s = s.replace(old, new)

open('hid_maus.py', 'w', encoding='utf-8').write(s)
print('PATCH_OK')
