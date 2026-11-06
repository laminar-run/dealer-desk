import http.client
import json
import socket
import sys
import threading
import time
import tkinter as tk
import unittest
from types import SimpleNamespace

from chaos.controls import Controls
from chaos.engine import ChaosEngine
from chaos.receiver import Receiver


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tcl()
        self.effects = []
        self.engine = ChaosEngine(self.root)

        def record_effect(*parameters):
            self.root.eval("info patchlevel")
            self.effects.append((parameters, threading.get_ident()))

        self.controls = SimpleNamespace(
            minimize=record_effect,
            move=record_effect,
            ignore_next_click=record_effect,
        )
        self.server = Receiver(self.engine, "test-key", self.controls)

    def tearDown(self):
        self.engine.close()
        self.server.close()
        self.controls = None
        self.root = None

    def request(self, body, key="test-key", route="/window/minimize", chunked=False):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.port, timeout=3
        )
        try:
            connection.request(
                "POST",
                route,
                body=[json.dumps(body).encode()] if chunked else json.dumps(body),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def drain(self):
        deadline = time.monotonic() + 1
        while not self.engine.pending.empty() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.001)
        self.assertTrue(self.engine.pending.empty())

    def test_auth_and_typed_validation_never_execute(self):
        for body, key, route, code in [
            ({"timeoutMs": 5}, "wrong", "/window/minimize", 401),
            ({"timeoutMs": True}, "test-key", "/window/minimize", 422),
            ({"timeoutMs": 30001}, "test-key", "/window/minimize", 422),
            (
                {"timeoutMs": 1, "extra": "x" * 2048},
                "test-key",
                "/window/minimize",
                422,
            ),
            ({"timeoutMs": "5"}, "test-key", "/window/minimize", 422),
            ({"timeoutMs": 5}, "test-key", "/WINDOW/minimize", 404),
            ({"timeoutMs": 5}, "test-key", "/window/minimize/", 404),
            ({"timeoutMs": 5, "x": 2**31, "y": 0}, "test-key", "/window/move", 422),
            ({"timeoutMs": 5, "x": 1, "y": False}, "test-key", "/window/move", 422),
        ]:
            with self.subTest(body=body, key=key, route=route):
                self.assertEqual(self.request(body, key, route)[0], code)
                self.assertTrue(self.engine.pending.empty())
        self.assertEqual(self.effects, [])

    def test_accepted_before_tk_busy_and_expiry_without_late_effect(self):
        self.engine.stop()
        self.assertEqual(
            self.request({"timeoutMs": 500, "x": -10, "y": 20}, route="/window/move"),
            (202, {"status": "accepted"}),
        )
        self.assertEqual(self.effects, [])
        self.assertEqual(
            self.request({"timeoutMs": 500}),
            (503, {"status": "rejected", "code": "busy"}),
        )
        self.drain()
        self.assertEqual(self.effects, [((-10, 20), threading.get_ident())])
        self.assertEqual(self.request({"timeoutMs": 1})[0], 202)
        time.sleep(0.02)
        self.drain()
        self.assertEqual(len(self.effects), 1)
        self.assertEqual(self.request({"timeoutMs": 500}, chunked=True)[0], 202)
        self.drain()
        self.assertEqual(len(self.effects), 2)

    def test_failed_callback_is_logged_and_polling_survives(self):
        def fail():
            raise RuntimeError("callback probe")

        self.controls.minimize = fail
        self.assertEqual(self.request({"timeoutMs": 500})[0], 202)
        with self.assertLogs(level="ERROR") as logged:
            self.drain()
        self.assertIn("callback probe", logged.output[0])
        self.assertEqual(
            self.request({"timeoutMs": 500}, route="/input/ignore-next-click")[0], 202
        )
        self.drain()
        self.assertEqual(self.effects, [((), threading.get_ident())])

    def test_slow_clients_do_not_block_other_requests_or_shutdown(self):
        for initial in (
            b"POST /window/minimize HTTP/1.1\r\nX-Trickle: ",
            (
                b"POST /window/minimize HTTP/1.1\r\nAuthorization: Bearer test-key\r\n"
                b"Content-Type: application/json\r\nContent-Length: 2048\r\n\r\n{"
            ),
        ):
            with socket.create_connection(("127.0.0.1", self.server.port)) as slow:
                slow.sendall(initial)
                self.assertEqual(self.request({"timeoutMs": 1})[0], 202)
                time.sleep(0.02)
                self.drain()
                self.assertEqual(self.effects, [])
        self.engine.close()
        self.assertEqual(
            self.request({"timeoutMs": 500}),
            (503, {"status": "rejected", "code": "shutting_down"}),
        )
        self.server.close()
        self.assertFalse(self.server.thread.is_alive())
        self.assertIsNone(self.server.engine)
        self.assertIsNone(self.server.controls)


@unittest.skipUnless(sys.platform == "win32", "Requires Windows Tk mouse bindings")
class ClickTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.root.withdraw()
        self.window = tk.Toplevel(self.root)
        self.controls = Controls(self.root)
        self.controls.set_primary(self.window)
        self.window.grab_set()
        self.calls = []
        self.button = tk.Button(
            self.window, text="Click", command=lambda: self.calls.append("command")
        )
        self.button.pack()
        self.root.update()

    def tearDown(self):
        if hasattr(self, "root"):
            self.root.destroy()

    def click(self, button, release=True):
        button.event_generate("<Enter>", x=2, y=2)
        button.event_generate("<ButtonPress-1>", x=2, y=2)
        if release:
            button.event_generate("<ButtonRelease-1>", x=2, y=2)
        self.root.update()

    def test_widget_press_and_button_release_are_swallowed_once(self):
        self.button.bind("<ButtonPress-1>", lambda event: self.calls.append("press"))
        self.assertIsNone(self.controls.ignore_next_click())
        with self.assertRaisesRegex(RuntimeError, "already_armed"):
            self.controls.ignore_next_click()
        self.click(self.button)
        self.assertEqual(self.calls, [])
        self.click(self.button)
        self.assertEqual(self.calls, ["press", "command"])

    def test_dynamic_widget_lost_release_and_other_modal(self):
        self.controls.ignore_next_click()
        dynamic = tk.Button(
            self.window, text="New", command=lambda: self.calls.append("dynamic")
        )
        dynamic.pack()
        self.root.update()
        self.click(dynamic, release=False)
        self.assertEqual(self.calls, [])
        self.click(dynamic)
        self.assertEqual(self.calls, ["dynamic"])
        modal = tk.Toplevel(self.root)
        modal.grab_set()
        with self.assertRaisesRegex(RuntimeError, "no_eligible_window"):
            self.controls.ignore_next_click()
        modal.destroy()
        self.window.grab_set()
        self.assertIsNone(self.controls.ignore_next_click())

    def test_minimize_and_move_restore_preserve_client_size(self):
        import win32con
        import win32gui

        self.window.geometry("320x240+100+100")
        self.root.update()
        for state in ("normal", "zoomed"):
            with self.subTest(state=state):
                self.window.resizable(state == "zoomed", state == "zoomed")
                self.window.state(state)
                self.root.update()
                hwnd = win32gui.GetAncestor(self.window.winfo_id(), win32con.GA_ROOT)
                self.assertEqual(self.window.state(), state)
                self.assertIsNone(self.controls.minimize())
                self.assertTrue(win32gui.IsIconic(hwnd))
                self.assertIsNone(self.controls.move(140, 110))
                self.root.update()
                self.assertFalse(win32gui.IsIconic(hwnd))
                self.assertEqual(win32gui.GetWindowRect(hwnd)[:2], (140, 110))
                self.assertEqual(self.window.winfo_width(), 320)
                self.assertEqual(self.window.winfo_height(), 240)
