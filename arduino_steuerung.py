# arduino_steuerung.py - Arduino-HID Kommunikation
import serial, struct, time

class ArduinoSteuerung:
    def __init__(self, port="COM3", baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.verbunden = False

    def verbinde(self):
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.5)
            time.sleep(2)  # Arduino Reset abwarten
            self.verbunden = True
            print(f"✅ Arduino verbunden: {self.port}")
            return True
        except Exception as e:
            print(f"⚠️  Arduino nicht gefunden ({self.port}): {e}")
            print("   → Verwende Software-Klicks (pyautogui)")
            self.verbunden = False
            return False

    def trenne(self):
        if self.ser:
            self.ser.close()
            self.verbunden = False
            print("🔌 Arduino getrennt.")

    # Absolute Bewegung + Klick
    def klicke_abs(self, x, y):
        if not self.verbunden:
            return False
        # MOVE_ABS + CLICK
        packet = struct.pack("<Bhh", 0x01, x, y)  # MOVE_ABS
        self.ser.write(packet)
        time.sleep(0.02)
        self.ser.write(bytes([0x02]))  # CLICK
        return True

    def bewege_abs(self, x, y):
        if not self.verbunden:
            return False
        packet = struct.pack("<Bhh", 0x01, x, y)  # MOVE_ABS
        self.ser.write(packet)
        return True

    def klicke(self):
        if not self.verbunden:
            return False
        self.ser.write(bytes([0x02]))  # CLICK
        return True
