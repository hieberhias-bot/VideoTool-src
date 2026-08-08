#!/usr/bin/env python3
"""maus_dispatcher.py - Prioritaets-Arbitrierung fuer die gemeinsam genutzte
HID-Maus-Verbindung.

Ein serieller COM-Port (die Arduino-HID-Maus, siehe hid_maus.py) erlaubt nur
EINE offene Verbindung/EINEN Nutzer gleichzeitig - ohne Koordination wuerden
parallel laufende Bot-Skripte (siehe makro_manager.py) und der Fisch-Bot sich
gegenseitig die Befehle auf der Leitung durcheinanderbringen. MausDispatcher
loest das, ohne die Verbindung selbst zu kennen: er vergibt nur das Recht,
sie gerade zu benutzen.

Arbitrierung ist KOOPERATIV, kein Preemptive-Locking: ein Halter, der die
Maus bereits bekommen hat, wird nicht mitten in einer Aktion unterbrochen
(das koennte eine Mausbewegung/einen Klick im Spiel korrumpieren) - er gibt
sie explizit per maus_freigeben() zurueck, typischerweise sofort nach einer
einzelnen Klick-/Beweg-Aktion. "Hoehere Prioritaet gewinnt bei Konflikt"
bedeutet deshalb: sobald die Maus frei wird UND mehrere Anfragen gerade
warten, kommt die mit der hoechsten Prioritaet zuerst dran - nicht, dass eine
hochpriorisierte Anfrage eine laufende Aktion abbricht.
"""

import threading
import time

PRIORITAET_HOCH = "HOCH"
PRIORITAET_MITTEL = "MITTEL"
PRIORITAET_NIEDRIG = "NIEDRIG"

# Niedrigerer Rang = hoehere Prioritaet (gewinnt zuerst). Unbekannte/leere
# Prioritaeten fallen auf MITTEL zurueck, statt einen Fehler auszuloesen -
# ein Makro mit einem Tippfehler in der Prioritaet soll nicht deadlocken.
_PRIORITAET_RANG = {PRIORITAET_HOCH: 0, PRIORITAET_MITTEL: 1, PRIORITAET_NIEDRIG: 2}


def _rang(prioritaet):
    return _PRIORITAET_RANG.get(prioritaet, _PRIORITAET_RANG[PRIORITAET_MITTEL])


class MausDispatcher:
    """Arbitriert den Zugriff auf EINE gemeinsame HID-Maus-Verbindung
    zwischen mehreren Threads (parallele Makros + Fisch-Bot).

    Absichtlich kein einfacher threading.Lock: bei Konflikt soll die Anfrage
    mit der hoechsten Prioritaet gewinnen, nicht zwingend die zuerst
    wartende. threading.Condition erlaubt es, beim Aufwachen (nach
    notify_all()) erneut zu pruefen, ob gerade eine wartende Anfrage mit
    hoeherer Prioritaet ansteht, und in dem Fall weiterzuschlafen (siehe
    maus_holen()).
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._belegt = False
        self._wartende_raenge = []  # Rang-Werte aller AKTUELL wartenden Anfragen

    def maus_verfuegbar(self):
        """True, wenn die Maus gerade von niemandem gehalten wird.

        Reine Momentaufnahme - zwischen dieser Abfrage und einem folgenden
        maus_holen() kann sich der Zustand aendern (siehe maus_holen() fuer
        den eigentlich sicheren Weg, die Maus zu bekommen)."""
        with self._cond:
            return not self._belegt

    def maus_holen(self, prioritaet=PRIORITAET_MITTEL, timeout=None):
        """Blockiert, bis die Maus frei ist UND keine wartende Anfrage mit
        hoeherer Prioritaet ansteht, dann belegt sie sie fuer den Aufrufer.

        Args:
            prioritaet: PRIORITAET_HOCH/MITTEL/NIEDRIG (oder die entsprechenden
                Strings "HOCH"/"MITTEL"/"NIEDRIG") - je hoeher, desto eher
                gewinnt diese Anfrage bei einem Konflikt um die naechste
                Vergabe.
            timeout: maximale Wartezeit in Sekunden, oder None fuer
                unbegrenztes Warten.

        Returns:
            bool: True, wenn die Maus tatsaechlich belegt wurde - dann MUSS
                der Aufrufer sie spaeter per maus_freigeben() zurueckgeben
                (am besten in einem try/finally). False bei Timeout - die
                Maus wurde in diesem Fall NICHT belegt, maus_freigeben() darf
                dann NICHT aufgerufen werden.
        """
        rang = _rang(prioritaet)
        ende = None if timeout is None else time.time() + timeout

        with self._cond:
            self._wartende_raenge.append(rang)
            try:
                while True:
                    hoechste_wartende = min(self._wartende_raenge)
                    if not self._belegt and rang <= hoechste_wartende:
                        self._belegt = True
                        return True
                    if ende is not None:
                        rest = ende - time.time()
                        if rest <= 0:
                            return False
                        self._cond.wait(rest)
                    else:
                        self._cond.wait()
            finally:
                # Eigener Rang steht waehrend des Wartens (und nur solange)
                # in der Liste - egal ob durch return True/False oder eine
                # Exception verlassen, immer aufraeumen (sonst wuerde ein
                # abgebrochener Warte-Versuch fuer immer als "wartend" zaehlen
                # und andere Anfragen blockieren).
                self._wartende_raenge.remove(rang)

    def maus_freigeben(self):
        """Gibt die Maus wieder frei und weckt alle wartenden Threads, damit
        sie erneut pruefen koennen, ob sie jetzt an der Reihe sind.

        Darf nur aufgerufen werden, nachdem maus_holen() True geliefert hat
        (am besten aus dem finally-Zweig desselben try-Blocks) - ein
        ueberzaehliger Aufruf wuerde faelschlich signalisieren, dass die Maus
        frei ist, obwohl sie das (aus Sicht eines anderen, tatsaechlichen
        Halters) nicht ist.
        """
        with self._cond:
            self._belegt = False
            self._cond.notify_all()
