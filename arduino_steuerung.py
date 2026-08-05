# arduino_steuerung.py - Arduino-HID Kommunikation
import serial, struct, time

# Arduino-Protokoll (mouse_relay.ino)
COMMAND_LDOWN   = 0
COMMAND_LUP     = 1
COMMAND_MOUSEMOVE = 2
MAX_PACKET_SIZE = 8

class ArduinoSteuerung:
    def __init__(self, port="COM6", baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.verbunden = False

    def verbinde(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.5)
            time.sleep(2)
            self.verbunden = True
            print(f"Arduino verbunden: {self.port}")
            return True
        except Exception as e:
            print(f"Arduino nicht gefunden ({self.port}): {e}")
            print("Verwende Software-Klicks (pyautogui)")
            self.verbunden = False
            return False

    def trenne(self):
        if self.ser:
            self.ser.close()
            self.verbunden = False
            print("Arduino getrennt.")

    def _packet(self, cmd, x=0, y=0):
        return struct.pack("<BhhBBB", cmd, x, y, 0, 0, 0)

    def bewege_abs(self, x, y):
        if not self.verbunden:
            return False
        packet = self._packet(COMMAND_MOUSEMOVE, x, y)
        self.ser.write(packet)
        return True

    def klicke(self):
        if not self.verbunden:
            return False
        self.ser.write(self._packet(COMMAND_LDOWN))
        time.sleep(0.02)
        self.ser.write(self._packet(COMMAND_LUP))
        return True

    def klicke_abs(self, x, y):
        if not self.verbunden:
            return False
        self.bewege_abs(x, y)
        time.sleep(0.02)
        self.klicke()
        return True
