# -*- coding: utf-8 -*-
import sys, traceback, io

pfad = 'command_center.py'
src = io.open(pfad, encoding='utf-8').read()

# Tkinter-ReportCallback einfuegen, der Fehler in Datei schreibt
alt = 'if __name__ == "__main__":'
neu = '''def _report_callback(exc, val, tb):
    with open("tk_error.log", "a") as f:
        f.write("".join(traceback.format_exception(exc, val, tb)))
        f.write("\\n---\\n")

if __name__ == "__main__":
    import tkinter as tk
    try:
        from tkinter import Tk
        Tk.report_callback_exception = _report_callback
    except Exception:
        pass'''
if alt in src:
    src = src.replace(alt, neu, 1)
    io.open(pfad, 'w', encoding='utf-8').write(src)
    print('PATCH_OK')
else:
    print('ALT_TEXT_NICHT_GEFUNDEN')
