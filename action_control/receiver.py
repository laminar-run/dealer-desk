"""Opt-in DealerDesk test inbox. No installed action integration is required."""
import ctypes
import json
import logging
import os
from pathlib import Path
import queue
import threading
import time
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID


ACTION = "dealerdesk.critical-error"


def session_id(pid):
    value = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(pid, ctypes.byref(value)):
        raise OSError("Cannot resolve Windows session")
    return value.value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Receiver:
    def __init__(self, root, directory, origin):
        self.root, self.directory, self.origin = root, directory, origin
        self.pid = os.getpid()
        self.results = queue.Queue()
        self.busy = False
        self.closed = False
        self.dispatched = {}

    def verify(self, request):
        if set(request) != {"attemptId", "token", "action", "pid"}:
            raise ValueError("Invalid request fields")
        attempt = request["attemptId"]
        if str(UUID(attempt)) != attempt or request["action"] != ACTION or type(request["pid"]) is not int or request["pid"] != self.pid:
            raise ValueError("Invalid request target")
        token = request["token"]
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise ValueError("Invalid token")
        req = Request(f"{self.origin}/api/injected-actions/attempts/{attempt}", headers={"Authorization": f"Bearer {token}"})
        with build_opener(NoRedirect()).open(req, timeout=3) as response:
            status = json.loads(response.read(16384))
        deadline = status.get("deadlineAt")
        if status.get("active") is not True or type(deadline) not in (int, float) or not time.time() * 1000 < deadline:
            raise ValueError("Attempt is inactive or expired")
        return deadline

    def poll(self):
        if self.closed:
            return
        try:
            try:
                path, deadline = self.results.get_nowait()
            except queue.Empty:
                pass
            else:
                self.busy = False
                now = time.time() * 1000
                self.dispatched = {attempt: expiry for attempt, expiry in self.dispatched.items() if now < expiry}
                attempt = path.name.removesuffix(".request.claimed")
                try:
                    if deadline is not None and time.time() * 1000 < deadline and attempt not in self.dispatched:
                        self.dispatched[attempt] = deadline
                        from chaos.scenarios import scenario_critical_error
                        scenario_critical_error(self.root, immediate=True)
                finally:
                    path.unlink(missing_ok=True)
            if not self.busy:
                for path in self.directory.glob("*.request.json"):
                    claimed = path.with_suffix(".claimed")
                    try:
                        path.rename(claimed)
                    except FileNotFoundError:
                        continue
                    self.busy = True
                    threading.Thread(target=self.process, args=(claimed,), daemon=True).start()
                    break
        except Exception:
            logging.exception("DealerDesk test inbox failed")
        finally:
            self.root.after(100, self.poll)

    def process(self, path):
        deadline = None
        try:
            if path.stat().st_size > 8192:
                raise ValueError("Request too large")
            request = json.loads(path.read_text(encoding="utf-8"))
            if path.name != f'{request["attemptId"]}.request.claimed':
                raise ValueError("Attempt filename mismatch")
            deadline = self.verify(request)
        except Exception:
            logging.warning("Rejected DealerDesk test request")
        self.results.put((path, deadline))

    def close(self, event):
        if event.widget is not self.root:
            return
        self.closed = True
        ready = self.directory / "ready.json"
        try:
            if json.loads(ready.read_text()) == {"pid": self.pid}:
                ready.unlink()
        except (OSError, ValueError):
            pass
        finally:
            if hasattr(self, "mutex"):
                self.mutex.Close()


def start_test_inbox(root):
    origin = os.environ.get("INJECTED_ACTION_MIDDLEWARE_ORIGIN")
    if not origin:
        return
    parsed = urlsplit(origin)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Middleware URL must be a trusted origin")
    if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("HTTP middleware origin must be loopback")
    import win32event
    import win32api
    mutex = win32event.CreateMutex(None, False, "Local\\MinicorDealerDeskTestInbox")
    if win32api.GetLastError() == 183:
        mutex.Close()
        raise RuntimeError("Another DealerDesk test inbox is active")
    directory = Path(os.environ["LOCALAPPDATA"]) / "Minicor" / "DealerDesk" / "inbox" / str(session_id(os.getpid()))
    directory.mkdir(parents=True, exist_ok=True)
    ready = directory / "ready.json"
    for pattern in ("*.request.json", "*.claimed"):
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)
    receiver = Receiver(root, directory, origin.rstrip("/"))
    receiver.mutex = mutex
    temp = directory / f"ready.{os.getpid()}.tmp"
    temp.write_text(json.dumps({"pid": os.getpid()}))
    os.replace(temp, ready)
    root.bind("<Destroy>", receiver.close, add="+")
    root.after(100, receiver.poll)
    return receiver
