from pynput import mouse
import time

clicks = []
def on_click(x, y, button, pressed):
    if pressed:
        clicks.append((x, y))
        print("CLICK bei", x, y)
    if len(clicks) >= 2:
        return False

print("Bitte klicke 2x innerhalb von 10 Sekunden...")
l = mouse.Listener(on_click=on_click)
l.start()
time.sleep(10)
l.stop()
print("Empfangen:", len(clicks), "Klicks")
