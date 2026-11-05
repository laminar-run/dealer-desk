"""DealerDesk 98 - Entry Point."""
import os
import sys

# Ensure the project root is on sys.path when launched from a shortcut
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import tkinter as tk
from db.connection import init_db
from db.seed import seed


def _launch_login(root: tk.Tk, controls):
    from ui.login import LoginWindow

    def on_login_success(user: dict):
        from ui.dashboard import DashboardWindow
        from chaos.engine import ChaosEngine

        dashboard = DashboardWindow(root, user, on_logout=lambda: _launch_login(root, controls))

        controls.set_primary(dashboard)
        engine = ChaosEngine(root, on_logout=lambda: _kick_to_login(dashboard, root, controls))
        if _get_chaos_setting("master_enabled") == "1":
            engine.start()

    login = LoginWindow(root, on_success=on_login_success, on_primary=controls.set_primary)
    controls.set_primary(login)


def _kick_to_login(dashboard, root, controls):
    try:
        dashboard.destroy()
    except Exception:
        pass
    _launch_login(root, controls)


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

    from chaos.controls import Controls
    controls = Controls(root)
    publication = None
    receiver = None
    try:
        if os.name == "nt":
            import secrets
            from chaos.publication import Publication
            from chaos.receiver import Receiver
            from chaos.scenarios import inject_critical_error

            publication = Publication()
            key = secrets.token_urlsafe(32)
            receiver = Receiver(root, key, {
                "/window/move": controls.move,
                "/window/minimize": controls.minimize,
                "/input/ignore-next-click": controls.ignore_next_click,
                "/dms/critical-error": lambda parameters: inject_critical_error(root),
            })
            publication.publish(receiver.http.server_port, key)
        _launch_login(root, controls)
        root.mainloop()
    finally:
        if receiver:
            receiver.close()
        if publication:
            publication.close()


if __name__ == "__main__":
    main()
