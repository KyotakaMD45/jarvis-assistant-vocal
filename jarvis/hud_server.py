"""Tiny local web server for the HUD.

- serves the static page from jarvis/hud/
- pushes live events (state, audio level, conversation, stats) with Server-Sent Events
- receives commands typed in the HUD

Bound to 127.0.0.1 only, and every request must carry a random per-session token,
so other websites open in a browser cannot read the conversation or send commands.
"""
from __future__ import annotations

import json
import mimetypes
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jarvis.logger import get_logger

log = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "hud"
MAX_CLIENT_QUEUE = 500


class HudServer:
    def __init__(self, hud_config: dict, on_command=None, on_action=None):
        self.hud_config = hud_config
        self.on_command = on_command          # callable(text) for commands typed in the HUD
        self.on_action = on_action            # callable(name, value) for HUD buttons
        self.token = secrets.token_urlsafe(24)
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._snapshot: dict[str, dict] = {}  # last value of "sticky" events for late clients
        self._history: list[dict] = []        # conversation log replayed to new clients
        self._server: ThreadingHTTPServer | None = None
        self.port = 0

    # -- publishing ----------------------------------------------------------------------
    STICKY = {"state", "stats", "status", "config"}         # last value sent to new pages
    REPLAY = {"boot", "ready", "log", "log_append", "log_end"}  # full history sent to new pages

    def publish(self, event: str, data: dict | None = None) -> None:
        message = {"type": event, **(data or {})}
        with self._lock:
            if event == "status" and "status" in self._snapshot:
                self._snapshot["status"] = {**self._snapshot["status"], **message}
            elif event in self.STICKY:
                self._snapshot[event] = message
            if event in self.REPLAY:
                self._history.append(message)
                del self._history[:-200]
            clients = list(self._clients)
        for client in clients:
            try:
                client.put_nowait(message)
            except queue.Full:
                pass  # a stalled page must never block Jarvis

    # -- lifecycle -----------------------------------------------------------------------
    def start(self) -> str:
        server_ref = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep the console clean
                pass

            def _authorized(self, query: dict) -> bool:
                host = self.headers.get("Host", "")
                if host not in (f"127.0.0.1:{server_ref.port}", f"localhost:{server_ref.port}"):
                    return False
                token = self.headers.get("X-Jarvis-Token") or (query.get("token") or [""])[0]
                return secrets.compare_digest(token, server_ref.token)

            def _send(self, code: int, body: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path in ("/", "/index.html"):
                    if not self._authorized(query):
                        return self._send(403, b"forbidden")
                    return self._static("index.html")
                if url.path == "/events":
                    if not self._authorized(query):
                        return self._send(403, b"forbidden")
                    return self._events()
                # Static assets (css/js) are not secret; the token protects data and commands.
                name = url.path.lstrip("/")
                if name in ("hud.css", "hud.js"):
                    return self._static(name)
                return self._send(404, b"not found")

            def do_POST(self):  # noqa: N802
                url = urlparse(self.path)
                if url.path not in ("/api/command", "/api/action") or not self._authorized({}):
                    return self._send(403, b"forbidden")
                try:
                    length = min(int(self.headers.get("Content-Length", 0)), 4000)
                    body = json.loads(self.rfile.read(length) or b"{}")
                except (ValueError, AttributeError):
                    return self._send(400, b"bad request")
                if url.path == "/api/action":
                    name = str(body.get("action", ""))[:40]
                    value = str(body.get("value", ""))[:300]
                    if name and server_ref.on_action:
                        threading.Thread(target=server_ref.on_action, args=(name, value), daemon=True).start()
                    return self._send(204, b"")
                text = str(body.get("text", "")).strip()[:500]
                if text and server_ref.on_command:
                    server_ref.on_command(text)
                return self._send(204, b"")

            def _static(self, name: str) -> None:
                path = STATIC_DIR / name
                try:
                    body = path.read_bytes()
                except OSError:
                    return self._send(404, b"not found")
                content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
                if content_type.startswith("text/") or name.endswith(".js"):
                    content_type += "; charset=utf-8"
                self._send(200, body, content_type)

            def _events(self) -> None:
                client: queue.Queue = queue.Queue(maxsize=MAX_CLIENT_QUEUE)
                with server_ref._lock:
                    initial = [{"type": "config", **server_ref.hud_config}]
                    initial += [m for k, m in server_ref._snapshot.items() if k != "config"]
                    initial += list(server_ref._history)
                    server_ref._clients.append(client)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    for message in initial:
                        self.wfile.write(f"data: {json.dumps(message)}\n\n".encode())
                    self.wfile.flush()
                    while True:
                        try:
                            message = client.get(timeout=15)
                            payload = f"data: {json.dumps(message)}\n\n"
                        except queue.Empty:
                            payload = ": keep-alive\n\n"
                        self.wfile.write(payload.encode())
                        self.wfile.flush()
                except (OSError, ValueError):
                    pass  # page closed or reloaded
                finally:
                    with server_ref._lock:
                        if client in server_ref._clients:
                            server_ref._clients.remove(client)
                    self.close_connection = True

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, name="hud-server", daemon=True).start()
        log.info("HUD server on port %d", self.port)
        return self.url

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?token={self.token}"

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # -- background publishers -----------------------------------------------------------
    def start_stats(self, interval: float = 2.0) -> None:
        from jarvis.system_stats import SystemStats

        def loop():
            stats = SystemStats()
            stats.read()
            while True:
                time.sleep(interval)
                self.publish("stats", stats.read())

        threading.Thread(target=loop, name="hud-stats", daemon=True).start()
