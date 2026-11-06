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


def _launch_login(root: tk.Tk, controls, engine):
    from ui.login import LoginWindow

    engine.stop()
    engine.on_logout = None

    def on_login_success(user: dict):
        from ui.dashboard import DashboardWindow

        dashboard = DashboardWindow(
            root, user, on_logout=lambda: _launch_login(root, controls, engine)
        )

        controls.set_primary(dashboard)
        engine.on_logout = lambda: _kick_to_login(dashboard, root, controls, engine)
        engine.reload()

    login = LoginWindow(
        root, on_success=on_login_success, on_primary=controls.set_primary
    )
    controls.set_primary(login)


def _kick_to_login(dashboard, root, controls, engine):
    try:
        dashboard.destroy()
    except Exception:
        pass
    _launch_login(root, controls, engine)


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
    from chaos.engine import ChaosEngine

    controls = Controls(root)
    engine = ChaosEngine(root)
    publication = None
    receiver = None
    try:
        if os.name == "nt":
            import secrets

            from chaos.publication import Publication
            from chaos.receiver import Receiver

            publication = Publication()
            key = secrets.token_urlsafe(32)
            receiver = Receiver(engine, key, controls)
            publication.publish(receiver.port, key)
        _launch_login(root, controls, engine)
        root.mainloop()
    finally:
        engine.close()
        controls.set_primary(None)
        try:
            if receiver:
                receiver.close()
        finally:
            if publication:
                publication.close()


if __name__ == "__main__":
    main()
