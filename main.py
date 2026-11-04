"""DealerDesk 98 - Entry Point."""
import logging
import os
import sys

# Ensure the project root is on sys.path when launched from a shortcut
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import tkinter as tk
from db.connection import init_db
from db.seed import seed


def _launch_login(root: tk.Tk):
    from ui.login import LoginWindow

    def on_login_success(user: dict):
        from ui.dashboard import DashboardWindow
        from chaos.engine import ChaosEngine

        dashboard = DashboardWindow(root, user, on_logout=lambda: _launch_login(root))

        engine = ChaosEngine(root, on_logout=lambda: _kick_to_login(dashboard, root))
        if _get_chaos_setting("master_enabled") == "1":
            engine.start()

    LoginWindow(root, on_success=on_login_success)


def _kick_to_login(dashboard, root):
    try:
        dashboard.destroy()
    except Exception:
        pass
    _launch_login(root)


def _get_chaos_setting(key):
    try:
        from db.connection import get_connection
        conn = get_connection()
        row = conn.execute("SELECT value FROM chaos_settings WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else "0"
    except Exception:
        return "0"


def main():
    init_db()
    seed()

    root = tk.Tk()
    root.withdraw()  # Hidden root - acts as parent for all Toplevel windows

    ico = os.path.join(_HERE, "assets", "dms.ico")
    if os.path.exists(ico):
        try:
            root.iconbitmap(ico)
        except Exception:
            pass

    try:
        from action_control.receiver import start_test_inbox
        start_test_inbox(root)
    except Exception:
        logging.exception("Cannot start optional action tools")
    _launch_login(root)
    root.mainloop()


if __name__ == "__main__":
    main()
