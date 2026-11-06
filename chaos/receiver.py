import asyncio
import hmac
import json
import queue
import socket
import threading
import time
from collections.abc import Callable, Mapping

import uvicorn
from fastapi import FastAPI, Request
from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse

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
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.router.redirect_slashes = False
        for path in actions:
            app.add_api_route(path, self.accept, methods=["POST"])
        config = uvicorn.Config(
            app,
            loop="asyncio",
            ws="none",
            lifespan="off",
            proxy_headers=False,
            access_log=False,
            log_config=None,
            timeout_graceful_shutdown=0.5,
        )
        self.server = uvicorn.Server(config)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.startup_error = None
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(("127.0.0.1", 0))
            self.port = self.socket.getsockname()[1]
            self.thread = threading.Thread(target=self._serve, daemon=True)
            self.thread.start()
            deadline = time.monotonic() + 5
            while not self.server.started and self.thread.is_alive():
                if time.monotonic() >= deadline:
                    break
                self.thread.join(0.01)
            if not self.server.started:
                self.server.should_exit = True
                self.thread.join(2)
                raise RuntimeError("Chaos startup failed") from self.startup_error
        except BaseException:
            self.socket.close()
            self.root = None
            self.actions = {}
            raise
        self.poll = root.after(10, self._drain)

    def _serve(self):
        try:
            with self.socket:
                self.server.run(sockets=[self.socket])
        except BaseException as error:
            self.startup_error = error

    async def _body(self, request):
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 2048:
                raise OverflowError
            body.extend(chunk)
        return body

    async def accept(self, request: Request):
        code, status, reason = await self._accept(request)
        body = {"status": status}
        if reason:
            body["code"] = reason
        return JSONResponse(body, status_code=code)

    async def _accept(self, request):
        authorization = request.headers.get("Authorization", "")
        if not hmac.compare_digest(
            authorization.encode(), f"Bearer {self.key}".encode()
        ):
            return 401, "rejected", "unauthorized"
        try:
            media_type = request.headers.get("Content-Type", "").split(";", 1)[0]
            if media_type.strip().lower() != "application/json":
                raise ValueError
            parameters = json.loads(await asyncio.wait_for(self._body(request), 2))
            if not isinstance(parameters, dict):
                raise ValueError
            timeout_ms = parameters.pop("timeoutMs", None)
            if type(timeout_ms) is not int or not 1 <= timeout_ms <= 30000:
                raise ValueError
            invoke = self.actions[request.url.path](parameters)
        except OverflowError:
            return 413, "rejected", "body_too_large"
        except (ValueError, RecursionError, asyncio.TimeoutError, ClientDisconnect):
            return 400, "rejected", "invalid_request"
        with self.admission:
            if self.closed:
                return 503, "rejected", "shutting_down"
            work = Work(invoke, timeout_ms)
            try:
                self.pending.put_nowait(work)
            except queue.Full:
                return 503, "rejected", "busy"
        return await asyncio.to_thread(work.wait)

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
        self.server.should_exit = True
        self.thread.join(2)
        if self.thread.is_alive():
            raise RuntimeError("Chaos listener failed to stop")
        self.root = None
        self.actions = {}
