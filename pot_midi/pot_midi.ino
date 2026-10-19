// Педаль (потенциометр на GPIO3) -> сырое значение АЦП 0..4095 текстом по USB-сериалу.
// Вся калибровка и маппинг в MIDI делается на ПК в pot_bridge.
// Формат: одна строка на значение, например "2047\n".
const int POT_PIN = 3;
const int DEADBAND = 3;        // шлём, только если изменилось больше чем на 2 единицы
const int LOOP_MS = 10;        // ~100 раз в секунду
const int HEARTBEAT_MS = 500;  // повтор текущего значения, чтобы мост после подключения сразу его знал

int hist[5];
int histLen = 0;
int histPos = 0;
int lastSent = -1000;
unsigned long lastSendMs = 0;

int readSmoothed() {
  long s = 0;
  for (int i = 0; i < 32; i++) s += analogRead(POT_PIN);
  return s / 32;
}

// медиана из последних 5 сглаженных значений, гасит одиночные выбросы
int median5(int v) {
  hist[histPos] = v;
  histPos = (histPos + 1) % 5;
  if (histLen < 5) histLen++;
  int a[5];
  for (int i = 0; i < histLen; i++) a[i] = hist[i];
  for (int i = 1; i < histLen; i++) {
    int x = a[i], j = i - 1;
    while (j >= 0 && a[j] > x) { a[j + 1] = a[j]; j--; }
    a[j + 1] = x;
  }
  return a[histLen / 2];
}

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
}

void loop() {
  unsigned long t0 = millis();
  int raw = median5(readSmoothed());

  if (abs(raw - lastSent) >= DEADBAND || t0 - lastSendMs >= HEARTBEAT_MS) {
    Serial.println(raw);
    lastSent = raw;
    lastSendMs = t0;
  }

  unsigned long spent = millis() - t0;
  if (spent < LOOP_MS) delay(LOOP_MS - spent);
}
