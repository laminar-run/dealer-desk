import http.client
import json
import socket
import sys
import threading
import time
import tkinter as tk
import unittest
from dataclasses import dataclass

from chaos.actions import MoveParams, NoParams, bind_action, parse_move, parse_no_params
from chaos.controls import Controls
from chaos.receiver import Receiver, Work


class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tcl()
        self.effects = []

        def record_effect(parameters):
            self.effects.append(parameters)
            return 200, "completed", None

        self.server = Receiver(
            self.root,
            "test-key",
            {
                "/window/minimize": bind_action(parse_no_params, record_effect),
                "/window/move": bind_action(parse_move, record_effect),
            },
        )

    def tearDown(self):
        self.server.close()

    def request(self, body, key="test-key", route="/window/minimize"):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.http.server_port, timeout=3
        )
        try:
            connection.request(
                "POST",
                route,
                body=json.dumps(body),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_auth_validation_and_expired_http_never_execute(self):
        for body, key, route, code in [
            ({"timeoutMs": 5}, "wrong", "/window/minimize", 401),
            ({"timeoutMs": True}, "test-key", "/window/minimize", 400),
            ({"timeoutMs": 30001}, "test-key", "/window/minimize", 400),
            ({"timeoutMs": 1, "extra": 0}, "test-key", "/window/minimize", 400),
            ({"timeoutMs": 5}, "test-key", "/WINDOW/minimize", 404),
            ({"timeoutMs": 5, "x": 2**31, "y": 0}, "test-key", "/window/move", 400),
        ]:
            with self.subTest(body=body, key=key, route=route):
                self.assertEqual(self.request(body, key, route)[0], code)
                self.assertTrue(self.server.pending.empty())
        self.assertEqual(
            self.request({"timeoutMs": 5}),
            (504, {"status": "rejected", "code": "expired"}),
        )
        self.server._drain()
        self.assertEqual(self.effects, [])

    def test_completed_http_waits_for_effect_and_started_timeout_is_unknown(self):
        @dataclass(frozen=True)
        class MessageParams:
            message: str

        parsed = []

        def parse_message(parameters):
            if set(parameters) != {"message"} or type(parameters["message"]) is not str:
                raise ValueError
            result = MessageParams(parameters["message"])
            parsed.append((result, threading.get_ident()))
            return result

        def show_message(parameters: MessageParams):
            self.assertEqual(responses, [])
            self.root.eval("info patchlevel")
            self.effects.append((parameters, threading.get_ident()))
            return 200, "completed", None

        self.server.actions = {
            "/test/message": bind_action(parse_message, show_message)
        }
        self.assertEqual(
            self.request({"timeoutMs": 500, "message": 42}, route="/test/message")[0],
            400,
        )
        self.assertTrue(self.server.pending.empty())
        self.assertEqual(self.effects, [])
        responses = []
        caller = threading.Thread(
            target=lambda: responses.append(
                self.request(
                    {"timeoutMs": 500, "message": "Hello"}, route="/test/message"
                )
            )
        )
        caller.start()
        work = self.server.pending.get(timeout=1)
        self.assertEqual(responses, [])
        self.server.pending.put_nowait(work)
        deadline = time.monotonic() + 1
        while not responses and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.001)
        caller.join(1)
        self.assertEqual(self.effects, [(parsed[0][0], threading.get_ident())])
        self.assertIs(self.effects[0][0], parsed[0][0])
        self.assertEqual(self.effects[0][0], MessageParams("Hello"))
        self.assertEqual(parsed[0][1], self.server.thread.ident)
        self.assertEqual(responses, [(200, {"status": "completed"})])
        for result in ((200, "completed", None), (409, "rejected", "already_armed")):
            work = Work(lambda result=result: result, 50)
            self.assertTrue(work.start())
            self.assertEqual(work.wait(), (504, "unknown", "action_running"))
            self.assertFalse(work.start())
            while time.monotonic() <= work.deadline:
                time.sleep(0.001)
            work.finish(result)
            self.assertEqual(work.wait(), (504, "unknown", "action_running"))

    def test_start_expiry_race_has_one_winner(self):
        for _ in range(100):
            work = Work(lambda: (200, "completed", None), 1)
            barrier = threading.Barrier(2)
            started = []

            def run(work=work, barrier=barrier, started=started):
                barrier.wait()
                if work.start():
                    started.append(True)
                    work.finish((200, "completed", None))

            worker = threading.Thread(target=run)
            worker.start()
            barrier.wait()
            result = work.wait()
            worker.join()
            if result[1] == "rejected":
                self.assertFalse(started)
                self.assertEqual(result[2], "expired")
            else:
                self.assertTrue(started)
                self.assertIn(result[1], ("completed", "unknown"))
        work = Work(lambda: (200, "completed", None), 1)
        while time.monotonic() < work.deadline:
            time.sleep(0.001)
        self.assertFalse(work.start())
        self.assertEqual(work.wait(), (504, "rejected", "expired"))

    def test_trickled_headers_and_body_release_the_serial_worker(self):
        for initial in (
            b"POST /window/minimize HTTP/1.0\r\nX-Trickle: ",
            (
                b"POST /window/minimize HTTP/1.0\r\nAuthorization: Bearer test-key\r\n"
                b"Content-Type: application/json\r\nContent-Length: 2048\r\n\r\n{"
            ),
        ):
            with self.subTest(initial=initial):
                responses = []
                with socket.create_connection(self.server.http.server_address) as slow:
                    slow.sendall(initial)
                    caller = threading.Thread(
                        target=lambda responses=responses: responses.append(
                            self.request({"timeoutMs": 5})
                        )
                    )
                    caller.start()
                    deadline = time.monotonic() + 2.2
                    while time.monotonic() < deadline:
                        try:
                            slow.sendall(b" ")
                        except OSError:
                            break
                        time.sleep(0.05)
                    caller.join(0.3)
                    completed = responses[:]
                caller.join(1)
                self.assertEqual(
                    completed, [(504, {"status": "rejected", "code": "expired"})]
                )
                self.server._drain()
                self.assertEqual(self.effects, [])


@unittest.skipUnless(sys.platform == "win32", "Requires Windows Tk mouse bindings")
class ClickTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        self.tk = tk
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
        self.assertEqual(self.controls.ignore_next_click(NoParams())[0], 200)
        self.assertEqual(
            self.controls.ignore_next_click(NoParams())[2], "already_armed"
        )
        self.click(self.button)
        self.assertEqual(self.calls, [])
        self.click(self.button)
        self.assertEqual(self.calls, ["press", "command"])

    def test_dynamic_widget_lost_release_and_other_modal(self):
        self.controls.ignore_next_click(NoParams())
        dynamic = self.tk.Button(
            self.window, text="New", command=lambda: self.calls.append("dynamic")
        )
        dynamic.pack()
        self.root.update()
        self.click(dynamic, release=False)
        self.assertEqual(self.calls, [])
        self.click(dynamic)
        self.assertEqual(self.calls, ["dynamic"])
        modal = self.tk.Toplevel(self.root)
        modal.grab_set()
        self.assertEqual(
            self.controls.ignore_next_click(NoParams())[2], "no_eligible_window"
        )
        modal.destroy()
        self.window.grab_set()
        self.assertEqual(self.controls.ignore_next_click(NoParams())[0], 200)

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
                self.assertEqual(self.controls.minimize(NoParams())[0], 200)
                self.assertTrue(win32gui.IsIconic(hwnd))
                self.assertEqual(self.controls.move(MoveParams(140, 110))[0], 200)
                self.root.update()
                self.assertFalse(win32gui.IsIconic(hwnd))
                self.assertEqual(win32gui.GetWindowRect(hwnd)[:2], (140, 110))
                self.assertEqual(self.window.winfo_width(), 320)
                self.assertEqual(self.window.winfo_height(), 240)
