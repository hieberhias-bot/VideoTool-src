# hid_maus.py - Serielle Kommunikation mit einem HID-Maus-Geraet (Text-Protokoll)
"""Modul fuer die serielle Steuerung eines USB-HID-Maus-Geraets.

Im Gegensatz zu ``arduino_steuerung.py`` (binaeres struct-Protokoll) spricht
dieses Modul ein einfaches, zeilenbasiertes Text-Protokoll: Es sendet Befehle
wie ``"CLICK\\n"`` und wartet bei Klicks auf eine Bestaetigung des Geraets
(z.B. ``"CLICKED"``). Die Verbindung laeuft mit 115200 Baud.
"""

import serial


class HidMaus:
    """Steuert ein serielles HID-Maus-Geraet ueber ein Text-Protokoll.

    Die Befehle werden als ASCII-Zeilen gesendet. Bei Klicks wird auf eine
    Bestaetigung des Geraets gewartet; bewegt sich das Geraet nicht (kein
    ``verbunden``), werfen die Methoden entsprechende Fehler.

    Attribute:
        port (str): Der serielle Port (z.B. ``"COM6"`` oder ``"/dev/ttyACM0"``).
        ser (serial.Serial): Das offene serielle Verbindungsobjekt.
    """

    BAUDRATE = 115200
    TIMEOUT = 1  # Sekunden

    def __init__(self, port):
        """Oeffnet die serielle Verbindung zum HID-Geraet.

        Args:
            port (str): Serieller Port des Geraets (z.B. ``"COM6"``).

        Raises:
            ConnectionError: Wenn der Port nicht geoeffnet werden kann
                (Geraet nicht vorhanden, belegt oder falscher Port).
        """
        self.port = port
        self.ser = None
        try:
            self.ser = serial.Serial(port, self.BAUDRATE, timeout=self.TIMEOUT)
        except serial.SerialException as e:
            # SerialException in einen aussagekraeftigen ConnectionError uebersetzen,
            # damit aufrufender Code nur einen Fehlertyp behandeln muss.
            raise ConnectionError(
                "Konnte serielle Verbindung zu '%s' nicht oeffnen: %s" % (port, e)
            ) from e

    def _sende(self, befehl):
        """Sendet einen Textbefehl (fuegt Zeilenumbruch hinzu).

        Args:
            befehl (str): Der Befehl ohne Zeilenumbruch, z.B. ``"CLICK"``.

        Raises:
            ConnectionError: Wenn nicht geschrieben werden kann (Verbindung
                geschlossen oder Geraet getrennt).
        """
        if self.ser is None or not self.ser.is_open:
            raise ConnectionError("Serielle Verbindung ist nicht geoeffnet.")
        try:
            self.ser.write((befehl + "\n").encode("ascii"))
        except serial.SerialException as e:
            raise ConnectionError("Fehler beim Senden von '%s': %s" % (befehl, e)) from e

    def _warte_auf(self, erwartet):
        """Liest eine Antwortzeile und prueft auf die erwartete Bestaetigung.

        Args:
            erwartet (str): Erwarteter Bestaetigungstext, z.B. ``"CLICKED"``.

        Returns:
            bool: ``True`` wenn die Bestaetigung empfangen wurde, sonst ``False``
                (z.B. bei Timeout ohne passende Antwort).

        Raises:
            ConnectionError: Wenn beim Lesen ein serieller Fehler auftritt.
        """
        try:
            antwort = self.ser.readline().decode("ascii", errors="ignore").strip()
        except serial.SerialException as e:
            raise ConnectionError("Fehler beim Lesen der Bestaetigung: %s" % e) from e
        return antwort == erwartet

    def klick_links(self):
        """Fuehrt einen Linksklick aus und wartet auf Bestaetigung.

        Sendet ``"CLICK\\n"`` und erwartet die Antwort ``"CLICKED"``.

        Returns:
            bool: ``True`` wenn das Geraet den Klick bestaetigt hat, sonst
                ``False`` (Timeout oder unerwartete Antwort).

        Raises:
            ConnectionError: Bei Verbindungs-/Uebertragungsfehlern.
        """
        self._sende("CLICK")
        return self._warte_auf("CLICKED")

    def klick_rechts(self):
        """Fuehrt einen Rechtsklick aus und wartet auf Bestaetigung.

        Sendet ``"RCLICK\\n"`` und erwartet die Antwort ``"RCLICKED"``.

        Returns:
            bool: ``True`` wenn das Geraet den Klick bestaetigt hat, sonst
                ``False`` (Timeout oder unerwartete Antwort).

        Raises:
            ConnectionError: Bei Verbindungs-/Uebertragungsfehlern.
        """
        self._sende("RCLICK")
        return self._warte_auf("RCLICKED")

    def druecken(self):
        """Haelt die linke Maustaste gedrueckt (Maustaste unten halten).

        Sendet ``"DOWN\\n"``. Es wird keine Bestaetigung erwartet.

        Raises:
            ConnectionError: Bei Verbindungs-/Uebertragungsfehlern.
        """
        self._sende("DOWN")

    def loslassen(self):
        """Laesst die linke Maustaste wieder los.

        Sendet ``"UP\\n"``. Es wird keine Bestaetigung erwartet.

        Raises:
            ConnectionError: Bei Verbindungs-/Uebertragungsfehlern.
        """
        self._sende("UP")

    def schliessen(self):
        """Schliesst die serielle Verbindung sauber.

        Mehrfaches Aufrufen ist unschaedlich. Fehler beim Schliessen werden
        unterdrueckt, damit Aufraeumen (z.B. in ``finally``) nie fehlschlaegt.
        """
        if self.ser is not None:
            try:
                self.ser.close()
            except serial.SerialException:
                pass
            finally:
                self.ser = None
