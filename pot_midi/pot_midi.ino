// Потенциометр на GPIO3 -> MIDI CC по USB-сериалу (сырые MIDI-байты).
// На ПК мост pot_bridge.py перекидывает их в виртуальный порт loopMIDI.
const int POT_PIN = 3;
const byte MIDI_CH = 0;   // канал 1
const byte CC_NUM = 20;   // CC#20, свободный
const int HYST = 8;       // гистерезис в отсчётах АЦП, чтобы CC не дрожал

// Калибровка под педаль (замер pot_test):
//   упор 1 = ~3614 (3598..3626), дальше по ходу растёт до 4095 (потолок АЦП),
//   у упора 2 ползунок съезжает с дорожки и значение скачком падает в ~7.
// Рабочий кусок 3614..4095, сужен на ~3% с каждой стороны, чтобы в упорах было ровно 0 и 127.
const int RAW_MIN = 3630;
const int RAW_MAX = 4080;
// Всё ниже этого порога физически не может быть упором 1, значит это упор 2 (скачок).
const int OFF_TRACK = 3400;
const bool INVERT = false; // true, если CC идёт задом наперёд

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
  if (raw < OFF_TRACK) raw = 4095;
  raw = constrain(raw, RAW_MIN, RAW_MAX);

  if (abs(raw - lastRaw) >= HYST || raw == RAW_MIN || raw == RAW_MAX) {
    int cc = map(raw, RAW_MIN, RAW_MAX, 0, 127);
    if (INVERT) cc = 127 - cc;
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
