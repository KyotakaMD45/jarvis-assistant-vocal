"""iPhone (or any phone) remote for Apex, on the home Wi-Fi.

Off until the owner says "Apex, connecte mon iPhone". Then a small web server listens on the
local network (port 8770) and serves:
  GET  /?k=KEY          the phone page (conversation live, type or dictate commands)
  GET  /events?k=KEY    live events (Server-Sent Events), same as the PC interface
  POST /api/command     {"text": "..."}  run a command as if typed on the PC
  POST /api/ask         {"text": "..."}  run it and wait for Apex's answer -> {"reply": "..."}
                        (used by the Siri shortcut: "Dis Siri, Apex")
  POST /api/action      {"action": "repeat" | "toggle_listening" | "media"}
Every request needs the secret key (stored in state.json, changed by "déconnecte mon iPhone").
"""
from __future__ import annotations

import json
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from jarvis.logger import get_logger
from jarvis.state import load_state, save_state

log = get_logger(__name__)

PAGE = Path(__file__).resolve().parent / "hud" / "mobile.html"
PORT = 8770
ALLOWED_ACTIONS = {"repeat", "toggle_listening", "media", "listen"}


def remote_key(rotate: bool = False) -> str:
    key = load_state().get("remote_key")
    if rotate or not isinstance(key, str) or len(key) < 20:
        key = secrets.token_urlsafe(18)
        save_state(remote_key=key)
    return key


def local_ip() -> str:
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # UDP "connect" sends nothing; it only picks the interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


class RemoteServer:
    def __init__(self, hud_server, on_command, on_action, port: int = PORT, host: str = "0.0.0.0"):
        self.hud = hud_server
        self.on_command = on_command
        self.on_action = on_action
        self.port = port
        self.host = host  # 0.0.0.0 = reachable from the phone on the home network
        self.key = remote_key()
        self._clients: list[queue.Queue] = []
        self._waiters: list[dict] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        return f"http://{local_ip()}:{self.port}/?k={self.key}"

    @property
    def ask_url(self) -> str:
        return f"http://{local_ip()}:{self.port}/api/ask?k={self.key}"

    # -- events from the assistant (via the PC interface server) ---------------------------
    def on_event(self, message: dict) -> None:
        with self._lock:
            clients = list(self._clients)
            waiters = list(self._waiters)
        for client in clients:
            try:
                client.put_nowait(message)
            except queue.Full:
                pass
        kind, role = message.get("type"), message.get("role")
        for w in waiters:
            if w["done"].is_set():
                continue
            if kind == "log" and role == "jarvis":
                if message.get("streaming"):
                    w["id"], w["text"] = message.get("id"), message.get("text") or ""
                elif message.get("text"):
                    w["text"] = message["text"]
                    w["done"].set()
            elif kind == "log_append" and message.get("id") == w["id"]:
                w["text"] += message.get("text") or ""
            elif kind == "log_end" and message.get("id") == w["id"]:
                w["done"].set()

    def ask(self, text: str, timeout: float = 30.0) -> str:
        waiter = {"done": threading.Event(), "text": "", "id": None}
        with self._lock:
            self._waiters.append(waiter)
        try:
            self.on_command(text)
            waiter["done"].wait(timeout)
            return waiter["text"].strip() or "Apex n'a pas répondu à temps."
        finally:
            with self._lock:
                self._waiters.remove(waiter)

    # -- server ------------------------------------------------------------------------------
    def start(self) -> str:
        ref = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _authorized(self, query: dict) -> bool:
                key = self.headers.get("X-Apex-Key") or (query.get("k") or [""])[0]
                return bool(key) and secrets.compare_digest(key, ref.key)

            def _send(self, code: int, body: bytes, ctype: str = "text/plain; charset=utf-8") -> None:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path in ("/", "/index.html"):
                    # The page itself holds no data; it asks for the key (kept by the phone).
                    try:
                        return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                    except OSError:
                        return self._send(500, b"page missing")
                if url.path == "/events":
                    if not self._authorized(query):
                        return self._send(403, b"forbidden")
                    return self._events()
                return self._send(404, b"not found")

            def do_POST(self):  # noqa: N802
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path not in ("/api/command", "/api/ask", "/api/action") or not self._authorized(query):
                    return self._send(403, b"forbidden")
                try:
                    length = min(int(self.headers.get("Content-Length", 0)), 4000)
                    raw = self.rfile.read(length) or b"{}"
                    body = json.loads(raw) if raw.strip().startswith(b"{") else {"text": raw.decode("utf-8", "replace")}
                except (ValueError, AttributeError):
                    return self._send(400, b"bad request")
                if url.path == "/api/action":
                    name = str(body.get("action", ""))[:40]
                    if name in ALLOWED_ACTIONS and ref.on_action:
                        threading.Thread(target=ref.on_action, args=(name, ""), daemon=True).start()
                    return self._send(204, b"")
                text = str(body.get("text", "")).strip()[:500]
                if not text:
                    return self._send(400, b"empty")
                log.info("iPhone: %r", text)
                if url.path == "/api/ask":
                    reply = ref.ask(text)
                    data = json.dumps({"reply": reply}, ensure_ascii=False).encode("utf-8")
                    return self._send(200, data, "application/json; charset=utf-8")
                ref.on_command(text)
                return self._send(204, b"")

            def _events(self) -> None:
                client: queue.Queue = queue.Queue(maxsize=500)
                with ref.hud._lock:
                    initial = [m for k, m in ref.hud._snapshot.items() if k in ("state", "status")]
                    initial += [m for m in ref.hud._history if m.get("type") in ("log", "log_append", "log_end")][-60:]
                with ref._lock:
                    ref._clients.append(client)
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    for message in initial:
                        self.wfile.write(f"data: {json.dumps(message, ensure_ascii=False)}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    while True:
                        try:
                            message = client.get(timeout=15)
                            if message.get("type") == "level":
                                continue  # too chatty for a phone
                            self.wfile.write(f"data: {json.dumps(message, ensure_ascii=False)}\n\n".encode("utf-8"))
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (OSError, ValueError):
                    pass
                finally:
                    with ref._lock:
                        if client in ref._clients:
                            ref._clients.remove(client)

        self._server = ThreadingHTTPServer((self.host, self.port), Handler)
        self._server.daemon_threads = True
        threading.Thread(target=self._server.serve_forever, name="remote", daemon=True).start()
        self.hud.add_listener(self.on_event)
        log.info("iPhone remote listening on port %d", self.port)
        return self.url

    def stop(self) -> None:
        self.hud.remove_listener(self.on_event)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        log.info("iPhone remote stopped")


def make_qr(url: str, path: Path) -> Path:
    import qrcode

    img = qrcode.make(url, box_size=10, border=3)
    img.save(path)
    return path


def wait_ready(seconds: float = 0.2) -> None:
    time.sleep(seconds)
