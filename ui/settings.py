"""Settings / Chaos panel for DealerDesk 98."""
import tkinter as tk
from tkinter import messagebox
from ui import style
from ui.widgets import (
    w98_button, w98_label, w98_frame, w98_labelframe, w98_combobox, title_bar,
)
from db.connection import get_connection


# (setting_key, display name, description) - keys match chaos.engine SCENARIO_MAP
SCENARIOS = [
    ("random_dialog", "Random Dialog", "Pops 'DMS server connection lost' dialog (loops on Cancel)"),
    ("fake_freeze", "Fake Freeze", "Hangs the whole app for 3-10 seconds"),
    ("session_timeout", "Session Timeout", "Shows session expired, optionally logs out"),
    ("unexpected_save", "Unexpected Save Popup", "Shows spurious 'Record saved' message"),
    ("critical_error", "Critical Error Dialog", "Massive red ERROR popup with fake stack trace - Ignore/Retry/Report/OK"),
    ("field_corruption", "Field Corruption", "Appends garbage chars to focused field"),
    ("save_failure", "Save Failure", "Error dialog but write is silently dropped"),
    ("wrong_patient", "Wrong Customer Warning", "Warns that you may be on the wrong customer record"),
    ("bsod_overlay", "BSOD Overlay", "Full-screen fake Blue Screen of Death"),
    ("slow_progress", "Slow Progress Bar", "Modal 'Loading...' that crawls 30 seconds"),
]

FREQUENCIES = ["rare", "occasional", "frequent", "constant"]


def _load():
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM chaos_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def _save_key(key, value):
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO chaos_settings (key,value) VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()


class SettingsPanel(tk.Frame):
    def __init__(self, parent, dashboard):
        super().__init__(parent, bg=style.BG)
        self.dashboard = dashboard
        self._build()
        self._load_ui()

    def _build(self):
        title_bar(self, "  Settings").pack(fill=tk.X)
        outer = w98_frame(self)
        outer.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        master_lf = w98_labelframe(outer, text="Master Control")
        master_lf.pack(fill=tk.X, pady=(0, 8))
        master_row = w98_frame(master_lf)
        master_row.pack(fill=tk.X, padx=8, pady=6)

        self._master_var = tk.BooleanVar()
        tk.Checkbutton(master_row, text="  Enable Chaos Engine", variable=self._master_var,
                       font=style.FONT_BOLD, bg=style.BG, activebackground=style.BG,
                       name="chk_master_enabled", command=self._on_master_toggle).pack(side=tk.LEFT)

        w98_label(master_row, text="  Frequency:").pack(side=tk.LEFT, padx=(16, 0))
        self._freq_var = tk.StringVar()
        w98_combobox(master_row, textvariable=self._freq_var, values=FREQUENCIES,
                     name="cmb_frequency", width=14).pack(side=tk.LEFT, padx=4)

        w98_label(master_row, text="  Trigger:").pack(side=tk.LEFT, padx=(8, 0))
        self._trigger_var = tk.StringVar()
        w98_combobox(master_row, textvariable=self._trigger_var,
                     values=["event (on button clicks)", "time (timer-based)"],
                     name="cmb_trigger_mode", width=24).pack(side=tk.LEFT, padx=4)

        w98_button(master_row, "Apply", command=self._apply_master,
                   name="btn_apply_master", width=8).pack(side=tk.LEFT, padx=8)

        scenarios_lf = w98_labelframe(outer, text="Scenarios")
        scenarios_lf.pack(fill=tk.BOTH, expand=True)
        hdr = w98_frame(scenarios_lf)
        hdr.pack(fill=tk.X, padx=6, pady=(4, 0))
        tk.Label(hdr, text="On/Off", font=style.FONT_BOLD, bg=style.BG, width=6).pack(side=tk.LEFT)
        tk.Label(hdr, text="Scenario", font=style.FONT_BOLD, bg=style.BG, width=22, anchor="w").pack(side=tk.LEFT)
        tk.Label(hdr, text="Description", font=style.FONT_BOLD, bg=style.BG, anchor="w").pack(side=tk.LEFT)
        tk.Label(hdr, text="", bg=style.BG, width=10).pack(side=tk.RIGHT)
        tk.Frame(scenarios_lf, bg=style.BG_DARK, height=1).pack(fill=tk.X, padx=6, pady=2)

        self._scenario_vars = {}
        for key, name, desc in SCENARIOS:
            row = w98_frame(scenarios_lf)
            row.pack(fill=tk.X, padx=6, pady=1)
            var = tk.BooleanVar()
            self._scenario_vars[key] = var
            tk.Checkbutton(row, variable=var, bg=style.BG, activebackground=style.BG,
                           name=f"chk_{key}", command=lambda k=key, v=var: self._toggle_scenario(k, v)).pack(side=tk.LEFT)
            tk.Label(row, text=name, font=style.FONT_BOLD, bg=style.BG, width=22, anchor="w").pack(side=tk.LEFT)
            tk.Label(row, text=desc, font=style.FONT, bg=style.BG, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
            w98_button(row, "Fire Now", command=lambda k=key: self._fire_now(k),
                       name=f"btn_fire_{key}", width=9).pack(side=tk.RIGHT, padx=4)

        bot = w98_frame(outer)
        bot.pack(fill=tk.X, pady=(8, 0))
        w98_button(bot, "Save All Settings", command=self._save_all, name="btn_save_settings", width=16).pack(side=tk.LEFT, padx=4)
        w98_button(bot, "Reload", command=self._load_ui, name="btn_reload_settings", width=10).pack(side=tk.LEFT, padx=4)

    def _load_ui(self):
        settings = _load()
        self._master_var.set(settings.get("master_enabled", "0") == "1")
        self._freq_var.set(settings.get("frequency", "occasional"))
        tm = settings.get("trigger_mode", "event")
        self._trigger_var.set("event (on button clicks)" if tm == "event" else "time (timer-based)")
        for key, var in self._scenario_vars.items():
            var.set(settings.get(key, "0") == "1")

    def _on_master_toggle(self):
        self._apply_master()

    def _apply_master(self):
        enabled = self._master_var.get()
        _save_key("master_enabled", "1" if enabled else "0")
        freq = self._freq_var.get().strip()
        if freq in FREQUENCIES:
            _save_key("frequency", freq)
        mode = "event" if self._trigger_var.get().startswith("event") else "time"
        _save_key("trigger_mode", mode)
        try:
            from chaos.engine import get_engine
            engine = get_engine()
            if engine:
                engine.reload()
        except Exception:
            pass
        self.dashboard.status_bar.set(f"Chaos engine {'ENABLED' if enabled else 'DISABLED'}")

    def _toggle_scenario(self, key, var):
        _save_key(key, "1" if var.get() else "0")

    def _save_all(self):
        self._apply_master()
        for key, var in self._scenario_vars.items():
            _save_key(key, "1" if var.get() else "0")
        try:
            from chaos.engine import get_engine
            engine = get_engine()
            if engine:
                engine.reload()
        except Exception:
            pass
        messagebox.showinfo("Settings", "Settings saved successfully.", parent=self)
        self.dashboard.status_bar.set("Chaos settings saved.")

    def _fire_now(self, key):
        try:
            from chaos.engine import get_engine, SCENARIO_MAP
            engine = get_engine()
            if engine:
                engine.fire(key)
            else:
                import importlib
                dotted = SCENARIO_MAP.get(key)
                if dotted:
                    module_path, func_name = dotted.rsplit(".", 1)
                    mod = importlib.import_module(module_path)
                    getattr(mod, func_name)(root=tk._default_root)
        except Exception as e:
            messagebox.showerror("Error", f"Could not fire scenario: {e}", parent=self)
