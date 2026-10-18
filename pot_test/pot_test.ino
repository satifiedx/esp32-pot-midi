void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);
}
void loop() {
  long s = 0;
  for (int i = 0; i < 32; i++) s += analogRead(3);
  Serial.println(s / 32);
  delay(50);
}
