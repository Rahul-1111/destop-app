// D8 = button input (external 10k pulldown to GND) -> CYCLE START
// D9 = button input (external 10k pulldown to GND) -> CYCLE END
// D2 = output1 (stays HIGH until DECLAMP command received)
// D3 = output2 (HIGH for 500 ms only)
// D4 = output3 (HIGH on "OK", LOW on "FAIL")

const uint8_t PIN_BTN_START = 8;
const uint8_t PIN_BTN_END   = 9;
const uint8_t PIN_OUT1 = 2;
const uint8_t PIN_OUT2 = 3;
const uint8_t PIN_OUT3 = 4;

const unsigned long DEBOUNCE_MS = 50;

int lastRawStart = LOW;
int lastRawEnd   = LOW;
int stableStart  = LOW;
int stableEnd    = LOW;
unsigned long lastBounceStart = 0;
unsigned long lastBounceEnd   = 0;

bool cycleRunning = false;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN_START, INPUT);  // external pulldown resistor
  pinMode(PIN_BTN_END, INPUT);    // external pulldown resistor
  pinMode(PIN_OUT1, OUTPUT);
  pinMode(PIN_OUT2, OUTPUT);
  pinMode(PIN_OUT3, OUTPUT);

  digitalWrite(PIN_OUT1, LOW);
  digitalWrite(PIN_OUT2, LOW);
  digitalWrite(PIN_OUT3, LOW);
}

void loop() {
  // ---- START button handling (D8) ----
  int rawStart = digitalRead(PIN_BTN_START);
  if (rawStart != lastRawStart) lastBounceStart = millis();
  if ((millis() - lastBounceStart) > DEBOUNCE_MS) {
    if (rawStart != stableStart) {
      stableStart = rawStart;
      if (stableStart == HIGH && !cycleRunning) startCycle();
    }
  }
  lastRawStart = rawStart;

  // ---- END button handling (D9) ----
  int rawEnd = digitalRead(PIN_BTN_END);
  if (rawEnd != lastRawEnd) lastBounceEnd = millis();
  if ((millis() - lastBounceEnd) > DEBOUNCE_MS) {
    if (rawEnd != stableEnd) {
      stableEnd = rawEnd;
      if (stableEnd == HIGH) {
        Serial.println("CYCLE END");
      }
    }
  }
  lastRawEnd = rawEnd;

  // ---- serial command handling ----
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();  // remove CR/LF and spaces

    if (cmd.equalsIgnoreCase("DECLAMP")) {
      digitalWrite(PIN_OUT1, LOW);   // D2 LOW on DECLAMP
      Serial.println("DECLAMP RECEIVED");
    } 
    else if (cmd.equalsIgnoreCase("OK")) {
      digitalWrite(PIN_OUT3, HIGH);  // D4 HIGH on OK
      Serial.println("OK RECEIVED");
    } 
    else if (cmd.equalsIgnoreCase("FAIL")) {
      digitalWrite(PIN_OUT3, LOW);   // D4 LOW on FAIL
      Serial.println("FAIL RECEIVED");
    }
  }
}

void startCycle() {
  cycleRunning = true;
  Serial.println("CYCLE START");

  // D2 stays high
  digitalWrite(PIN_OUT1, HIGH);

  // after 1000 ms, set D3 high for 500 ms, then D3 low only
  delay(1000);
  digitalWrite(PIN_OUT2, HIGH);
  delay(500);
  digitalWrite(PIN_OUT2, LOW);

  cycleRunning = false;
}