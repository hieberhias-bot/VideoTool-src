#include <Mouse.h>

void setup() {
  Serial.begin(115200);
  Mouse.begin();
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);
  delay(500);
  digitalWrite(LED_BUILTIN, LOW);
}

void loop() {
  if (Serial.available() > 0) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    if (cmd == "CLICK") {
      Mouse.click(MOUSE_LEFT);
      Serial.println("OK");
    } else if (cmd == "RCLICK") {
      Mouse.click(MOUSE_RIGHT);
      Serial.println("OK");
    } else if (cmd == "DOWN") {
      Mouse.press(MOUSE_LEFT);
      Serial.println("OK");
    } else if (cmd == "UP") {
      Mouse.release(MOUSE_LEFT);
      Serial.println("OK");
    }
  }
}
