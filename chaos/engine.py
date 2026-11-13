"""ChaosEngine singleton - reads settings from DB and fires scenarios."""

import logging
import queue
import random
import threading
import time
import tkinter as tk
from collections.abc import Callable

from db.connection import get_connection

logger = logging.getLogger(__name__)
_engine_instance = None


def get_engine():
    return _engine_instance


def set_engine(engine):
    global _engine_instance
    _engine_instance = engine


FREQUENCY_INTERVALS = {
    "rare": (60, 180),
    "occasional": (20, 60),
    "frequent": (8, 20),
    "constant": (3, 8),
}

SCENARIO_MAP = {
    "random_dialog": "chaos.scenarios.scenario_random_dialog",
    "fake_freeze": "chaos.scenarios.scenario_fake_freeze",
    "session_timeout": "chaos.scenarios.scenario_session_timeout",
    "unexpected_save": "chaos.scenarios.scenario_unexpected_save",
    "critical_error": "chaos.scenarios.scenario_critical_error",
    "field_corruption": "chaos.scenarios.scenario_field_corruption",
    "save_failure": "chaos.scenarios.scenario_save_failure",
    "wrong_patient": "chaos.scenarios.scenario_wrong_patient",
    "bsod_overlay": "chaos.scenarios.scenario_bsod",
    "slow_progress": "chaos.scenarios.scenario_slow_progress",
}


def _load_settings():
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM chaos_settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


class ChaosEngine:
    def __init__(self, root, on_logout=None):
        self.root = root
        self.on_logout = on_logout
        self._timer = None
        self._running = False
        self.pending: queue.Queue[tuple[float, Callable[[], None]]] = queue.Queue(
            maxsize=1
        )
        self.closed = False
        self._admission = threading.Lock()
        self._poll = root.after(10, self._drain)
        set_engine(self)

    def submit(self, callback: Callable[[], None], timeout_ms: int) -> str | None:
        with self._admission:
            if self.closed:
                return "shutting_down"
            try:
                self.pending.put_nowait(
                    (time.monotonic() + timeout_ms / 1000, callback)
                )
            except queue.Full:
                return "busy"

    def _drain(self):
        try:
            deadline, callback = self.pending.get_nowait()
        except queue.Empty:
            pass
        else:
            if time.monotonic() < deadline:
                try:
                    callback()
                except Exception:
                    logger.exception("Chaos action failed")
        if not self.closed:
            self._poll = self.root.after(10, self._drain)

    def close(self):
        with self._admission:
            if self.closed:
                return
            self.closed = True
            try:
                self.pending.get_nowait()
            except queue.Empty:
                pass
        self.stop()
        try:
            self.root.after_cancel(self._poll)
        except tk.TclError:
            pass
        self.root = None
        self.on_logout = None
        set_engine(None)

    def start(self):
        self._running = True
        self._schedule_next()

    def stop(self):
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None

    def reload(self):
        """Re-read settings and restart timer."""
        self.stop()
        settings = _load_settings()
        if settings.get("master_enabled", "0") == "1":
            self.start()

    def _schedule_next(self):
        if not self._running:
            return
        settings = _load_settings()
        if settings.get("master_enabled", "0") != "1":
            self._running = False
            return
        freq = settings.get("frequency", "occasional")
        lo, hi = FREQUENCY_INTERVALS.get(freq, (20, 60))
        interval = random.uniform(lo, hi)
        self._timer = threading.Timer(interval, self._fire_random)
        self._timer.daemon = True
        self._timer.start()

    def _fire_random(self):
        settings = _load_settings()
        if settings.get("master_enabled", "0") != "1":
            self._running = False
            return
        enabled = [k for k in SCENARIO_MAP if settings.get(k, "0") == "1"]
        if not enabled:
            self._schedule_next()
            return
        scenario_key = random.choice(enabled)
        self.fire(scenario_key)
        self._schedule_next()

    def fire(self, scenario_key: str, **extra):
        """Immediately execute a named scenario."""
        import importlib

        dotted = SCENARIO_MAP.get(scenario_key)
        if not dotted:
            return
        module_path, func_name = dotted.rsplit(".", 1)
        try:
            mod = importlib.import_module(module_path)
            fn = getattr(mod, func_name)
            kwargs = {"root": self.root, **extra}
            if scenario_key == "session_timeout":
                kwargs["on_logout"] = self.on_logout
            fn(**kwargs)
        except Exception as e:
            print(f"[ChaosEngine] Error firing {scenario_key}: {e}")

    def on_event(self, event_type: str):
        """Called by UI on save/navigate/new_encounter to fire event-based scenarios."""
        settings = _load_settings()
        if settings.get("master_enabled", "0") != "1":
            return
        # In event mode: fire on any UI action.
        # In time mode: also fire on save for the "unexpected_save" scenario specifically.
        trigger_mode = settings.get("trigger_mode", "event")
        if trigger_mode == "time" and event_type not in ("save",):
            return
        enabled = [k for k in SCENARIO_MAP if settings.get(k, "0") == "1"]
        if not enabled:
            return
        scenario_key = random.choice(enabled)
        self.fire(scenario_key)
