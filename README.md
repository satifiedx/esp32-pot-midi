# esp32-pot-midi

Потенциометр на ESP32-C3 Super Mini → MIDI CC → FL Studio (или любая DAW).

У ESP32-C3 нет USB MIDI, поэтому плата шлёт MIDI-байты по USB-сериалу, а мост на ПК перекидывает их в виртуальный порт [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html).

```
потенциометр -> ESP32-C3 (GPIO3) -> USB COM -> pot_bridge.exe -> loopMIDI -> FL Studio
```

## Железо

- ESP32-C3 Super Mini
- Потенциометр B50K: средняя ножка → GPIO3, крайние → 3.3V и GND

## Прошивка

Плата: **ESP32C3 Dev Module**, **USB CDC On Boot = Enabled**.

```bash
arduino-cli core install esp32:esp32
arduino-cli compile --upload -p COM4 --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc pot_midi
```

Если `Failed to connect`: зажми BOOT, переподключи USB и повтори.

- `pot_midi/` шлёт CC#20 на 1-м канале, с гистерезисом.
- `pot_test/` для проверки: печатает сырые значения АЦП (0–4095).

## Запуск

1. Поставь и запусти loopMIDI, создай порт (кнопка **+**).
2. Воткни плату.
3. Запусти `pot_bridge.exe` из [Releases](../../releases) (или `python pot_bridge.py`).
   Сам находит плату (USB VID 303A) и первый порт loopMIDI.
   Можно указать вручную: `pot_bridge.exe COM4 "loopMIDI Port"`.

## FL Studio

1. **F10** → MIDI → **Input**: выбери `loopMIDI Port`, **Enable**. В Output его не включай.
2. В плагине правый клик по ручке → **Link to controller…** → крутани потенциометр → **Accept**.

## Сборка exe

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --console --name pot_bridge pot_bridge.py
```

## Нюанс

У ESP32-C3 АЦП с ослаблением 11 dB читает примерно до 2.5 В, поэтому верхняя четверть хода упирается в 127. Если нужен весь ход, поставь резистор ~15–22 кОм между 3.3V и крайней ножкой потенциометра.
