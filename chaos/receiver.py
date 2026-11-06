import hmac
import json
import queue
import socket
import threading
import time
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, HTTPServer

from chaos.actions import Prepare, Result


class Work:
    def __init__(self, invoke: Callable[[], Result], timeout_ms: int):
        self.invoke = invoke
        self.deadline = time.monotonic() + timeout_ms / 1000
        self.state = "pending"
        self.result = None
        self.finished_at = None
        self.lock = threading.Lock()
        self.done = threading.Event()

    def _finish(self, result):
        self.state = "finished"
        self.result = result
        self.finished_at = time.monotonic()
        self.done.set()

    def start(self):
        with self.lock:
            if self.state != "pending":
                return False
            if time.monotonic() >= self.deadline:
                self._finish((504, "rejected", "expired"))
                return False
            self.state = "started"
            return True

    def finish(self, result):
        with self.lock:
            self._finish(result)

    def cancel(self):
        with self.lock:
            if self.state == "pending":
                self._finish((503, "rejected", "shutting_down"))

    def wait(self):
        self.done.wait(max(0, self.deadline - time.monotonic()))
        with self.lock:
            if self.state == "pending":
                self._finish((504, "rejected", "expired"))
            if self.result and (
                self.result[2] in ("expired", "shutting_down")
                or self.finished_at <= self.deadline
            ):
                return self.result
            return 504, "unknown", "action_running"


class Receiver:
    def __init__(self, root, key, actions: Mapping[str, Prepare]):
        self.root = root
        self.key = key
        self.actions = actions
        self.pending = queue.Queue(maxsize=1)
        self.closed = False
        self.admission = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)
                self.read_deadline = time.monotonic() + 2
                self.read_timer = threading.Timer(2, self.expire_read)
                self.read_timer.start()

            def expire_read(self):
                try:
                    self.connection.shutdown(socket.SHUT_RD)
                except OSError:
                    pass

            def finish(self):
                self.read_timer.cancel()
                self.read_timer.join()
                super().finish()

            def log_message(self, *args):
                pass

            def send_error(self, code, message=None, explain=None):
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b'{"status":"rejected","code":"invalid_request"}')
                self.close_connection = True

            def do_POST(self):
                try:
                    result = owner.accept(self)
                    code, status, reason = result
                    body = {"status": status}
                    if reason:
                        body["code"] = reason
                    payload = json.dumps(body).encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(payload)
                except (OSError, TimeoutError):
                    pass
                finally:
                    self.close_connection = True

        self.http = HTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=lambda: self.http.serve_forever(poll_interval=0.05), daemon=True
        )
        self.thread.start()
        self.poll = root.after(10, self._drain)

    def accept(self, request):
        authorization = request.headers.get("Authorization", "")
        if not hmac.compare_digest(
            authorization.encode(), f"Bearer {self.key}".encode()
        ):
            return 401, "rejected", "unauthorized"
        if request.path not in self.actions:
            return 404, "rejected", "unknown_route"
        try:
            length = int(request.headers.get("Content-Length", "-1"))
            if length > 2048:
                return 413, "rejected", "body_too_large"
            if length < 0 or request.headers.get("Transfer-Encoding"):
                raise ValueError
            if request.headers.get_content_type() != "application/json":
                raise ValueError
            parameters = json.loads(request.rfile.read(length))
            if not isinstance(parameters, dict):
                raise ValueError
            timeout_ms = parameters.pop("timeoutMs", None)
            if type(timeout_ms) is not int or not 1 <= timeout_ms <= 30000:
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            return 400, "rejected", "invalid_request"
        try:
            invoke = self.actions[request.path](parameters)
        except ValueError:
            return 400, "rejected", "invalid_request"
        request.read_timer.cancel()
        request.read_timer.join()
        if time.monotonic() >= request.read_deadline:
            return 400, "rejected", "invalid_request"
        with self.admission:
            if self.closed:
                return 503, "rejected", "shutting_down"
            work = Work(invoke, timeout_ms)
            try:
                self.pending.put_nowait(work)
            except queue.Full:
                return 503, "rejected", "busy"
        return work.wait()

    def _drain(self):
        try:
            work = self.pending.get_nowait()
        except queue.Empty:
            work = None
        if work and work.start():
            try:
                result = work.invoke()
            except Exception:
                result = (500, "unknown", "action_failed")
            work.finish(result)
        if not self.closed:
            self.poll = self.root.after(10, self._drain)

    def close(self):
        with self.admission:
            self.closed = True
            try:
                self.pending.get_nowait().cancel()
            except queue.Empty:
                pass
        self.root.after_cancel(self.poll)
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
