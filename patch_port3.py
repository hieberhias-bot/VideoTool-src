import re
s = open('command_center.py', encoding='utf-8').read()
s = s.replace('self.hid_port = "COM6"', 'self.hid_port = ""  # leer = Auto-Detect')
open('command_center.py', 'w', encoding='utf-8').write(s)
print('PATCH_OK')
