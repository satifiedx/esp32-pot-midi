"""Ядро моста: чтение платы, калибровка, маппинг пресета, вывод в MIDI.

raw (0..4095) -> калибровка -> позиция педали 0..100% -> пресет -> полутоны -> MIDI.
"""
import json
import math
import os
import sys
import threading
import time

import rtmidi
import serial
from serial.tools import list_ports

ESPRESSIF_VID = 0x303A
SEMI_RANGE = 24  # полная шкала выхода: -24..+24 полутона

DEFAULT_PRESETS = [
    {"name": "0→+12 к половине", "in_start": 0, "in_end": 50, "out_start": 0, "out_end": 12},
    {"name": "0→−12 к половине", "in_start": 0, "in_end": 50, "out_start": 0, "out_end": -12},
    {"name": "0→+24 полный", "in_start": 0, "in_end": 100, "out_start": 0, "out_end": 24},
    {"name": "0→−24 полный", "in_start": 0, "in_end": 100, "out_start": 0, "out_end": -24},
    {"name": "−24…+24 полный", "in_start": 0, "in_end": 100, "out_start": -24, "out_end": 24},
]
PRESET_DEFAULTS = {"in_start": 0, "in_end": 100, "deadzone": 3, "out_start": 0, "out_end": 12,
                   "curve": 0, "step": False}

DEFAULT_CONFIG = {
    "calibration": {"min": 0, "max": 4095, "invert": False},
    "last_preset": DEFAULT_PRESETS[0]["name"],
    "output": {"mode": "pb", "cc": 20, "channel": 1},
    "midi_port": "loopMIDI",
}


def base_dir():
    # конфиги лежат рядом с exe (или рядом со скриптом)
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(base_dir(), "config.json")
PRESETS_PATH = os.path.join(base_dir(), "presets.json")


def normalize_preset(p):
    out = dict(PRESET_DEFAULTS)
    out.update(p)
    return out


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    saved = load_json(CONFIG_PATH, {})
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def load_presets():
    presets = load_json(PRESETS_PATH, None)
    if not presets:
        presets = DEFAULT_PRESETS
    return [normalize_preset(p) for p in presets]


# ---------- маппинг ----------

def pedal_percent(raw, cal):
    lo, hi = cal["min"], cal["max"]
    p = 0.0 if hi <= lo else (raw - lo) / (hi - lo)
    p = min(1.0, max(0.0, p))
    if cal.get("invert"):
        p = 1.0 - p
    return p * 100.0


def preset_semitones(pct, pr):
    start = pr["in_start"] + pr["deadzone"]  # мёртвая зона: до неё выход ровно в стартовом значении
    end = pr["in_end"]
    if end <= start:
        t = 1.0 if pct >= end else 0.0
    else:
        t = min(1.0, max(0.0, (pct - start) / (end - start)))
    # кривая: -100 быстрее в начале, 0 линейно, +100 быстрее в конце
    t = t ** (4.0 ** (pr["curve"] / 100.0))
    v = pr["out_start"] + (pr["out_end"] - pr["out_start"]) * t
    if pr["step"]:
        v = math.floor(v + 0.5)
    return min(SEMI_RANGE, max(-SEMI_RANGE, v))


def semitones_to_pitchbend(semi):
    # 0 полутонов = ровно 8192, -24 = 0, +24 = 16383
    if semi >= 0:
        return 8192 + round(semi / SEMI_RANGE * 8191)
    return 8192 + round(semi / SEMI_RANGE * 8192)


def semitones_to_cc(semi):
    return round((semi + SEMI_RANGE) / (2 * SEMI_RANGE) * 127)


def midi_message(semi, out):
    ch = (int(out["channel"]) - 1) & 0x0F
    if out["mode"] == "cc":
        return [0xB0 | ch, int(out["cc"]) & 0x7F, semitones_to_cc(semi)]
    v = semitones_to_pitchbend(semi)
    return [0xE0 | ch, v & 0x7F, v >> 7]


# ---------- движок ----------

class Engine:
    def __init__(self, cfg, preset):
        self.cfg = cfg          # GUI заменяет словари целиком, чтение без локов
        self.preset = preset
        self.raw = None
        self.percent = 0.0
        self.semis = 0.0
        self.board = None       # COM-порт, если плата подключена
        self.board_error = ""
        self.midi_name = None   # имя MIDI-порта, если открыт
        self.cal_until = 0.0
        self.cal_min = self.cal_max = None

        self._midi = None
        self._midi_lock = threading.Lock()
        self._last_msg = None
        self._stop = threading.Event()
        threading.Thread(target=self._serial_loop, daemon=True).start()
        threading.Thread(target=self._midi_loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    # --- калибровка ---
    def start_calibration(self, seconds=5.0):
        self.cal_min = self.cal_max = None
        self.cal_until = time.monotonic() + seconds

    def calibrating(self):
        return time.monotonic() < self.cal_until

    def finish_calibration(self):
        """Если замер закончился, возвращает (min, max) или (None, None) без данных; иначе None."""
        if not self.cal_until or self.calibrating():
            return None
        self.cal_until = 0.0
        return (self.cal_min, self.cal_max)

    # --- обработка ---
    def recompute(self):
        if self.raw is None:
            return
        self.percent = pedal_percent(self.raw, self.cfg["calibration"])
        self.semis = preset_semitones(self.percent, self.preset)
        self._send(midi_message(self.semis, self.cfg["output"]))

    def _on_raw(self, raw):
        self.raw = raw
        if self.calibrating():
            self.cal_min = raw if self.cal_min is None else min(self.cal_min, raw)
            self.cal_max = raw if self.cal_max is None else max(self.cal_max, raw)
        self.recompute()

    # --- плата ---
    def _find_board(self):
        for p in list_ports.comports():
            if p.vid == ESPRESSIF_VID:
                return p.device
        return None

    def _serial_loop(self):
        while not self._stop.is_set():
            com = self._find_board()
            if not com:
                self.board, self.board_error = None, "не найдена"
                time.sleep(1)
                continue
            try:
                with serial.Serial(com, 115200, timeout=0.2) as ser:
                    self.board, self.board_error = com, ""
                    while not self._stop.is_set():
                        line = ser.readline().strip()
                        if line.isdigit():
                            self._on_raw(int(line))
            except serial.SerialException as e:
                busy = "denied" in str(e).lower() or "access" in str(e).lower()
                self.board, self.board_error = None, f"{com} занят другой программой" if busy else f"{com} отвалилась"
                time.sleep(1)

    # --- MIDI ---
    def _send(self, msg):
        if msg == self._last_msg:
            return
        with self._midi_lock:
            if self._midi is None:
                return
            try:
                self._midi.send_message(msg)
                self._last_msg = msg
            except rtmidi.RtMidiError:
                self._close_midi()

    def _close_midi(self):
        try:
            self._midi.close_port()
        except Exception:
            pass
        self._midi = None
        self.midi_name = None
        self._last_msg = None

    def _midi_loop(self):
        while not self._stop.is_set():
            want = self.cfg.get("midi_port", "loopMIDI").lower()
            try:
                ports = rtmidi.MidiOut().get_ports()
            except rtmidi.RtMidiError:
                ports = []
            match = next((i for i, n in enumerate(ports) if want in n.lower()), None)
            with self._midi_lock:
                if self._midi is not None and (match is None or ports[match] != self.midi_name):
                    self._close_midi()  # порт пропал (loopMIDI закрыли)
                if self._midi is None and match is not None:
                    try:
                        m = rtmidi.MidiOut()
                        m.open_port(match)
                        self._midi, self.midi_name = m, ports[match]
                    except rtmidi.RtMidiError:
                        self._midi = None
            if self._midi is not None and self._last_msg is None:
                self.recompute()  # после (пере)подключения сразу шлём текущее значение
            time.sleep(1)
