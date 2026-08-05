#define MOUSE_PIN 2
#define DEBOUNCE_MS 10
#define SEND_INTERVAL_MS 5

volatile unsigned long lastInterrupt = 0;
volatile unsigned long lastSend = 0;
volatile bool clickDetected = false;
volatile int clickCount = 0;

void setup() {
  pinMode(MOUSE_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(MOUSE_PIN), onMouseClick, FALLING);
  Serial.begin(115200);
}

void onMouseClick() {
  unsigned long now = millis();
  if (now - lastInterrupt > DEBOUNCE_MS) {
    lastInterrupt = now;
    clickDetected = true;
  }
}

void loop() {
  if (clickDetected) {
    clickCount++;
    clickDetected = false;
  }
  if (clickCount > 0 && millis() - lastSend > SEND_INTERVAL_MS) {
    Serial.println(clickCount);
    clickCount = 0;
    lastSend = millis();
  }
}
