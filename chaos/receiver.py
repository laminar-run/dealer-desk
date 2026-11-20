import hmac
import socket
import threading
import time
from collections.abc import Callable

import uvicorn
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from chaos.actions import ActionRequest, MoveRequest, ScenarioRequest
from chaos.controls import Controls
from chaos.engine import ChaosEngine
from chaos.scenarios import show_critical_error


class Receiver:
    def __init__(self, engine: ChaosEngine, key: str, controls: Controls):
        self.engine = engine
        self.controls = controls

        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
        app.router.redirect_slashes = False

        @app.middleware("http")
        async def authorize(request: Request, call_next):
            authorization = request.headers.get("Authorization", "")
            if not hmac.compare_digest(
                authorization.encode(), f"Bearer {key}".encode()
            ):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
            return await call_next(request)

        @app.post("/window/move")
        async def move(request: MoveRequest):
            return self._accept(
                request, lambda: self.controls.move(request.x, request.y)
            )

        @app.post("/window/minimize")
        async def minimize(request: ActionRequest):
            return self._accept(request, self.controls.minimize)

        @app.post("/input/ignore-next-click")
        async def ignore_next_click(request: ActionRequest):
            return self._accept(request, self.controls.ignore_next_click)

        @app.post("/dms/critical-error")
        async def critical_error(request: ActionRequest):
            return self._accept(request, lambda: show_critical_error(self.engine.root))

        @app.post("/dms/scenario")
        async def scenario(request: ScenarioRequest):
            extra = {"duration_ms": request.durationMs} if request.durationMs else {}
            return self._accept(
                request, lambda: self.engine.fire(request.scenario, **extra)
            )

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
        self.thread = None
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
                raise RuntimeError("Chaos startup failed") from self.startup_error
        except BaseException:
            self.close()
            raise

    def _serve(self):
        try:
            with self.socket:
                self.server.run(sockets=[self.socket])
        except BaseException as error:
            self.startup_error = error

    def _accept(self, request: ActionRequest, callback: Callable[[], None]):
        reason = self.engine.submit(callback, request.timeoutMs)
        if reason:
            return JSONResponse({"status": "rejected", "code": reason}, status_code=503)
        return JSONResponse({"status": "accepted"}, status_code=202)

    def close(self):
        self.server.should_exit = True
        if self.thread and self.thread.is_alive():
            self.thread.join(2)
        self.socket.close()
        self.engine = None
        self.controls = None
        if self.thread and self.thread.is_alive():
            raise RuntimeError("Chaos listener failed to stop")
