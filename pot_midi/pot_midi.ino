// Потенциометр на GPIO3 -> MIDI CC по USB-сериалу (сырые MIDI-байты).
// На ПК мост pot_bridge.py перекидывает их в виртуальный порт loopMIDI.
const int POT_PIN = 3;
const byte MIDI_CH = 0;   // канал 1
const byte CC_NUM = 20;   // CC#20, свободный
const int HYST = 10;      // гистерезис в отсчётах АЦП, чтобы CC не дрожал (шум ~±3)

int lastRaw = -1000;
int lastCc = -1;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
}

void loop() {
  long s = 0;
  for (int i = 0; i < 32; i++) s += analogRead(POT_PIN);
  int raw = s / 32;

  if (abs(raw - lastRaw) >= HYST || raw == 0 || raw == 4095) {
    int cc = constrain(map(raw, 0, 4095, 0, 127), 0, 127);
    if (cc != lastCc) {
      Serial.write(0xB0 | MIDI_CH);
      Serial.write(CC_NUM);
      Serial.write((byte)cc);
      lastCc = cc;
    }
    lastRaw = raw;
  }
  delay(2);
}
