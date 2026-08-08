import re
s = open('hid_maus.py', encoding='utf-8').read()
if 'def _port_auto_finden' not in s:
    block = '''

def _port_auto_finden():
    """Findet den Arduino Micro (HID-Maus) automatisch anhand VID/PID."""
    try:
        import serial.tools.list_ports as lp
        for p in lp.comports():
            if p.vid == 0x2341 and p.pid in (0x8037, 0x8036):
                return p.device
            if p.vid == 0x1B4F and p.pid == 0x9206:
                return p.device
    except Exception:
        pass
    return None
'''
    idx = s.find('class HIDMaus')
    if idx == -1:
        idx = len(s)
    s = s[:idx] + block + s[idx:]
    open('hid_maus.py', 'w', encoding='utf-8').write(s)
    print('PATCH_OK')
else:
    print('BEREITS_VORHANDEN')
