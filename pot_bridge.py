"""Мост: ESP32-C3 (MIDI-байты по USB-сериалу) -> виртуальный MIDI-порт loopMIDI.

Запуск: pot_bridge [COM-порт] [часть имени MIDI-порта]
Без аргументов сам ищет плату ESP32 (USB VID 303A) и первый порт loopMIDI.
Ctrl+C или закрыть окно чтобы выйти.
"""
import sys
import time

import rtmidi
import serial
from serial.tools import list_ports

ESPRESSIF_VID = 0x303A
COM = sys.argv[1] if len(sys.argv) > 1 else None
PORT_NAME = sys.argv[2] if len(sys.argv) > 2 else "loopMIDI"


def find_com():
    if COM:
        return COM
    for p in list_ports.comports():
        if p.vid == ESPRESSIF_VID:
            return p.device
    return None


def open_midi():
    warned = False
    while True:
        out = rtmidi.MidiOut()
        ports = out.get_ports()
        for i, name in enumerate(ports):
            if PORT_NAME.lower() in name.lower():
                out.open_port(i)
                print(f"MIDI -> {name}")
                return out
        if not warned:
            print(f"Жду MIDI-порт '{PORT_NAME}'... Запусти loopMIDI и создай порт. Есть: {ports}")
            warned = True
        del out
        time.sleep(2)


def bridge(midi, com):
    with serial.Serial(com, 115200, timeout=0.1) as ser:
        print(f"Слушаю {com}. Крути!")
        msg = []
        last_print = 0.0
        while True:
            # читаем сколько уже пришло (минимум 1 байт), а не ждём полный буфер
            for b in ser.read(ser.in_waiting or 1):
                if b & 0x80:  # статус-байт начинает новое сообщение
                    msg = [b]
                elif msg:
                    msg.append(b)
                if len(msg) == 3:
                    midi.send_message(msg)
                    now = time.monotonic()
                    if now - last_print > 0.05:  # консоль не чаще 20 раз в сек
                        print(f"CC{msg[1]} = {msg[2]:3d}   ", end="\r")
                        last_print = now
                    msg = []


def main():
    print("ESP Pot MIDI bridge")
    midi = open_midi()
    warned = False
    while True:
        com = find_com()
        if not com:
            if not warned:
                print("Жду плату ESP32... Воткни USB.")
                warned = True
            time.sleep(1)
            continue
        warned = False
        try:
            bridge(midi, com)
        except serial.SerialException as e:
            print(f"\n{com} отвалился ({e}), переподключаюсь...")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
