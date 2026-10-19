"""ESP Pot Pedal: GUI-мост педаль (ESP32-C3) -> loopMIDI -> FL Studio.

Плата шлёт сырое значение АЦП, всё остальное (калибровка, пресеты, вывод) здесь.
"""
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import pedal_core as core

PARAMS = [
    # ключ, подпись, от, до, шаг
    ("in_start", "Начало хода, %", 0, 100, 1),
    ("in_end", "Конец хода, %", 0, 100, 1),
    ("deadzone", "Мёртвая зона, %", 0, 50, 1),
    ("out_start", "Значение в начале, пт", -24, 24, 1),
    ("out_end", "Значение в конце, пт", -24, 24, 1),
]
TEXT_INPUTS = ("Entry", "TEntry", "Spinbox", "TSpinbox")  # в них цифры печатаются, не переключают пресет


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = core.load_config()
        self.presets = core.load_presets()
        self.loading = False
        self.save_job = None

        names = [p["name"] for p in self.presets]
        idx = names.index(self.cfg["last_preset"]) if self.cfg["last_preset"] in names else 0
        self.engine = core.Engine(self.cfg, dict(self.presets[idx]))

        root.title("ESP Pot Pedal")
        root.resizable(False, False)
        self._build()
        self._select_preset(idx)
        root.bind("<Key>", self._on_key)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._tick()

    # ---------- UI ----------
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        r = self.root

        st = ttk.Frame(r)
        st.grid(row=0, column=0, sticky="we", **pad)
        self.board_lbl = tk.Label(st, text="Плата: …", anchor="w")
        self.board_lbl.pack(side="left")
        self.midi_lbl = tk.Label(st, text="loopMIDI: …", anchor="e")
        self.midi_lbl.pack(side="right")

        mon = ttk.Frame(r)
        mon.grid(row=1, column=0, sticky="we", **pad)
        self.semi_lbl = tk.Label(mon, text="0.0", font=("Segoe UI", 40, "bold"))
        self.semi_lbl.pack()
        self.bar = ttk.Progressbar(mon, length=380, maximum=100)
        self.bar.pack(fill="x")
        self.pos_lbl = ttk.Label(mon, text="педаль 0%   raw —")
        self.pos_lbl.pack()

        cal = ttk.LabelFrame(r, text="Калибровка")
        cal.grid(row=2, column=0, sticky="we", **pad)
        self.cal_btn = ttk.Button(cal, text="Калибровать (5 с)", command=self._calibrate)
        self.cal_btn.grid(row=0, column=0, padx=6, pady=6)
        self.cal_lbl = ttk.Label(cal, text="")
        self.cal_lbl.grid(row=0, column=1, padx=6)
        self.invert = tk.BooleanVar(value=self.cfg["calibration"]["invert"])
        ttk.Checkbutton(cal, text="Инверсия", variable=self.invert,
                        command=self._on_invert).grid(row=0, column=2, padx=6)
        self._show_cal()

        pf = ttk.LabelFrame(r, text="Пресет  (1–9 — быстрый выбор)")
        pf.grid(row=3, column=0, sticky="we", **pad)
        self.combo = ttk.Combobox(pf, state="readonly", width=28)
        self.combo.grid(row=0, column=0, columnspan=3, sticky="we", padx=6, pady=6)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self._select_preset(self.combo.current()))
        ttk.Button(pf, text="Сохранить как…", command=self._save_as).grid(row=1, column=0, padx=4, pady=4)
        ttk.Button(pf, text="Переименовать", command=self._rename).grid(row=1, column=1, padx=4)
        ttk.Button(pf, text="Удалить", command=self._delete).grid(row=1, column=2, padx=4)

        self.vars = {}
        for i, (key, label, lo, hi, step) in enumerate(PARAMS):
            ttk.Label(pf, text=label).grid(row=2 + i, column=0, columnspan=2, sticky="w", padx=6)
            v = tk.IntVar()
            sp = ttk.Spinbox(pf, from_=lo, to=hi, increment=step, textvariable=v, width=6)
            sp.grid(row=2 + i, column=2, sticky="e", padx=6, pady=2)
            v.trace_add("write", self._on_param)
            self.vars[key] = v

        row = 2 + len(PARAMS)
        ttk.Label(pf, text="Кривая").grid(row=row, column=0, sticky="w", padx=6)
        self.curve = tk.IntVar()
        ttk.Scale(pf, from_=-100, to=100, variable=self.curve, length=160,
                  command=lambda _=None: self.curve.set(round(float(self.curve.get())))
                  ).grid(row=row, column=1, sticky="we")
        self.curve_lbl = ttk.Label(pf, text="линейная", width=16)
        self.curve_lbl.grid(row=row, column=2, sticky="e", padx=6)
        self.curve.trace_add("write", self._on_param)
        self.step = tk.BooleanVar()
        ttk.Checkbutton(pf, text="Шагать по целым полутонам", variable=self.step,
                        command=self._on_param).grid(row=row + 1, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        of = ttk.LabelFrame(r, text="Вывод в MIDI")
        of.grid(row=4, column=0, sticky="we", **pad)
        out = self.cfg["output"]
        self.mode = tk.StringVar(value=out["mode"])
        ttk.Radiobutton(of, text="Pitch Bend 14-bit", value="pb", variable=self.mode,
                        command=self._on_output).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Radiobutton(of, text="CC №", value="cc", variable=self.mode,
                        command=self._on_output).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        self.cc = tk.IntVar(value=out["cc"])
        ttk.Spinbox(of, from_=0, to=127, textvariable=self.cc, width=5).grid(row=1, column=1, sticky="w")
        ttk.Label(of, text="Канал").grid(row=0, column=2, sticky="e", padx=6)
        self.chan = tk.IntVar(value=out["channel"])
        ttk.Spinbox(of, from_=1, to=16, textvariable=self.chan, width=4).grid(row=0, column=3, sticky="w", padx=6)
        self.cc.trace_add("write", self._on_output)
        self.chan.trace_add("write", self._on_output)
        self.out_lbl = ttk.Label(of, text="")
        self.out_lbl.grid(row=1, column=2, columnspan=2, sticky="w", padx=6)

    def _refresh_combo(self):
        self.combo["values"] = [f"{i + 1}. {p['name']}" if i < 9 else p["name"]
                                for i, p in enumerate(self.presets)]

    # ---------- пресеты ----------
    def _select_preset(self, idx):
        if not 0 <= idx < len(self.presets):
            return
        self.cur = idx
        p = self.presets[idx]
        self._refresh_combo()
        self.combo.current(idx)
        self.loading = True
        for key, *_ in PARAMS:
            self.vars[key].set(p[key])
        self.curve.set(p["curve"])
        self.step.set(p["step"])
        self.loading = False
        self.cfg["last_preset"] = p["name"]
        self._apply_preset()

    def _on_param(self, *_):
        if self.loading:
            return
        p = self.presets[self.cur]
        try:
            for key, _l, lo, hi, _s in PARAMS:
                p[key] = max(lo, min(hi, int(self.vars[key].get())))
            p["curve"] = int(self.curve.get())
        except (tk.TclError, ValueError):
            return  # поле временно пустое, пока печатают
        p["step"] = bool(self.step.get())
        self._apply_preset()

    def _apply_preset(self):
        p = self.presets[self.cur]
        c = p["curve"]
        self.curve_lbl.config(text="линейная" if c == 0 else
                              ("быстрее в начале" if c < 0 else "быстрее в конце") + f" {abs(c)}")
        self.engine.preset = dict(p)  # применяется сразу
        self.engine.recompute()
        self._schedule_save()

    def _ask_name(self, title, initial=""):
        name = simpledialog.askstring(title, "Название пресета:", initialvalue=initial, parent=self.root)
        name = (name or "").strip()
        if not name:
            return None
        if any(p["name"] == name for p in self.presets):
            messagebox.showerror(title, "Пресет с таким названием уже есть.", parent=self.root)
            return None
        return name

    def _save_as(self):
        name = self._ask_name("Сохранить как", self.presets[self.cur]["name"] + " (копия)")
        if name:
            self.presets.append(dict(self.presets[self.cur], name=name))
            self._select_preset(len(self.presets) - 1)

    def _rename(self):
        name = self._ask_name("Переименовать", self.presets[self.cur]["name"])
        if name:
            self.presets[self.cur]["name"] = name
            self._select_preset(self.cur)

    def _delete(self):
        if len(self.presets) == 1:
            messagebox.showinfo("Удалить", "Последний пресет удалить нельзя.", parent=self.root)
            return
        if messagebox.askyesno("Удалить", f"Удалить «{self.presets[self.cur]['name']}»?", parent=self.root):
            del self.presets[self.cur]
            self._select_preset(min(self.cur, len(self.presets) - 1))

    def _on_key(self, e):
        if e.widget.winfo_class() in TEXT_INPUTS:
            return
        if e.char and e.char in "123456789":
            self._select_preset(int(e.char) - 1)

    # ---------- калибровка / вывод ----------
    def _calibrate(self):
        self.engine.start_calibration(5.0)
        self.cal_btn.state(["disabled"])

    def _show_cal(self):
        c = self.cfg["calibration"]
        self.cal_lbl.config(text=f"raw {c['min']} … {c['max']}")

    def _on_invert(self):
        self.cfg["calibration"]["invert"] = bool(self.invert.get())
        self.engine.recompute()
        self._schedule_save()

    def _on_output(self, *_):
        try:
            out = {"mode": self.mode.get(), "cc": max(0, min(127, int(self.cc.get()))),
                   "channel": max(1, min(16, int(self.chan.get())))}
        except (tk.TclError, ValueError):
            return
        self.cfg["output"] = out
        self.engine._last_msg = None  # форсим отправку в новом формате
        self.engine.recompute()
        self._schedule_save()

    # ---------- сохранение ----------
    def _schedule_save(self):
        if self.save_job:
            self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(500, self._save)

    def _save(self):
        self.save_job = None
        try:
            core.save_json(core.CONFIG_PATH, self.cfg)
            core.save_json(core.PRESETS_PATH, self.presets)
        except OSError as e:
            messagebox.showerror("Сохранение", f"Не удалось сохранить настройки:\n{e}", parent=self.root)

    def _on_close(self):
        self._save()
        self.engine.stop()
        self.root.destroy()

    # ---------- индикация ----------
    def _tick(self):
        eng = self.engine
        if eng.board:
            self.board_lbl.config(text=f"● Плата: {eng.board}", fg="#1a9c3c")
        else:
            self.board_lbl.config(text=f"● Плата: {eng.board_error or 'нет'}", fg="#c62828")
        if eng.midi_name:
            self.midi_lbl.config(text=f"● {eng.midi_name}", fg="#1a9c3c")
        else:
            self.midi_lbl.config(text="● loopMIDI: нет порта", fg="#c62828")

        s = eng.semis
        self.semi_lbl.config(text=f"{s:+.0f}" if float(s).is_integer() else f"{s:+.2f}")
        self.bar["value"] = eng.percent
        self.pos_lbl.config(text=f"педаль {eng.percent:5.1f}%   raw {eng.raw if eng.raw is not None else '—'}")
        out = self.cfg["output"]
        if out["mode"] == "pb":
            self.out_lbl.config(text=f"PB = {core.semitones_to_pitchbend(s)}")
        else:
            self.out_lbl.config(text=f"CC = {core.semitones_to_cc(s)}")

        res = eng.finish_calibration()
        if eng.calibrating():
            left = max(0.0, eng.cal_until - time.monotonic())
            self.cal_lbl.config(text=f"Качай педаль! {left:.1f} с   ({eng.cal_min} … {eng.cal_max})")
        elif res is not None:
            self.cal_btn.state(["!disabled"])
            if res[0] is not None and res[1] - res[0] >= 100:
                self.cfg["calibration"].update(min=res[0], max=res[1])
                eng.recompute()
                self._schedule_save()
            else:
                messagebox.showwarning("Калибровка", "Педаль почти не двигалась или нет данных от платы. "
                                       "Повтори и качай от упора до упора.", parent=self.root)
            self._show_cal()
        self.root.after(33, self._tick)


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
