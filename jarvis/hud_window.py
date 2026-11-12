"""Open the HUD in a lightweight window.

1. pywebview (uses the WebView2/Edge engine built into Windows 11, no Electron)
2. fallback: Microsoft Edge in "app mode" (a window without browser UI)
3. last resort: the default browser

Closing the window only hides it (Jarvis keeps running in the tray) unless the app is quitting.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path

from jarvis.logger import get_logger
from jarvis.paths import ROOT

log = get_logger(__name__)

EDGE_PATHS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


class HudWindow:
    def __init__(self, url: str, hud_cfg: dict, title: str = "K.N.U.L.L."):
        self.url = url
        self.cfg = hud_cfg
        self.title = title
        self._window = None
        self._edge: subprocess.Popen | None = None
        self._quit = threading.Event()
        self._on_ready: Callable[[], None] = lambda: None
        self.kind = ""
        self.visible = False

    # -- control from any thread ---------------------------------------------------------
    def show(self) -> None:
        if self._quit.is_set():
            return
        if self.kind == "webview" and self._window is not None:
            try:
                self._window.show()
                self._window.restore()
                self.visible = True
            except Exception:  # noqa: BLE001
                log.exception("Could not show the window")
        elif self.kind == "edge":
            if self._edge is None or self._edge.poll() is not None:
                self._launch_edge()
        elif self.kind == "browser":
            webbrowser.open(self.url)

    def minimize(self) -> None:
        if self.kind == "webview" and self._window is not None and self.visible:
            try:
                self._window.minimize()
            except Exception:  # noqa: BLE001
                log.exception("Could not minimize the window")

    def hide(self) -> None:
        if self.kind == "webview" and self._window is not None:
            try:
                self._window.hide()
                self.visible = False
            except Exception:  # noqa: BLE001
                log.exception("Could not hide the window")
        elif self.kind == "edge" and self._edge is not None and self._edge.poll() is None:
            self._edge.terminate()

    def quit(self) -> None:
        """Close for real and make run() return."""
        self._quit.set()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:  # noqa: BLE001
                pass
        if self._edge is not None and self._edge.poll() is None:
            self._edge.terminate()

    # -- main loop (main thread) -----------------------------------------------------------
    def run(self, on_ready: Callable[[], None] | None = None, start_hidden: bool = False) -> None:
        """Show the window and block until quit(). on_ready() runs once the page is displayed (8 s max)."""
        fired = threading.Event()

        def ready() -> None:
            if on_ready is not None and not fired.is_set():
                fired.set()
                on_ready()

        self._on_ready = ready
        timer = threading.Timer(8.0, ready)
        timer.daemon = True
        timer.start()
        if self._run_webview(start_hidden):
            return
        if self._run_edge(start_hidden):
            return
        self.kind = "browser"
        print(f"HUD: open {self.url.split('?')[0]} in your browser.")
        if not start_hidden:
            try:
                webbrowser.open(self.url)
            except Exception:  # noqa: BLE001
                pass
        ready()
        self._quit.wait()

    def _run_webview(self, start_hidden: bool) -> bool:
        log.info("Opening the HUD window")
        try:
            import webview
        except Exception as exc:  # noqa: BLE001
            log.warning("pywebview unavailable: %r", exc)
            return False
        try:
            self._window = webview.create_window(
                self.title, self.url,
                width=int(self.cfg["width"]), height=int(self.cfg["height"]),
                min_size=(760, 520), fullscreen=bool(self.cfg["fullscreen"]),
                maximized=bool(self.cfg["maximized"]) and not self.cfg["fullscreen"],
                background_color="#02060D", text_select=False, hidden=start_hidden,
            )
            self.kind = "webview"
            self.visible = not start_hidden

            def on_loaded(*_args) -> None:
                log.info("HUD page loaded")
                self._on_ready()

            def on_closing(*_args):
                if self._quit.is_set():
                    return True
                # The X button hides the window: Jarvis keeps running in the tray.
                threading.Thread(target=self.hide, daemon=True).start()
                return False

            self._window.events.loaded += on_loaded
            self._window.events.closing += on_closing
            webview.start(private_mode=True)  # blocks until quit()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("pywebview window failed, trying Edge app mode: %r", exc)
            self._window = None
            return False

    def _edge_path(self) -> Path | None:
        found = next((p for p in EDGE_PATHS if p.exists()), None)
        if found:
            return found
        which = shutil.which("msedge")
        return Path(which) if which else None

    def _launch_edge(self) -> bool:
        edge = self._edge_path()
        if not edge:
            return False
        args = [
            str(edge), f"--app={self.url}", f"--user-data-dir={ROOT / '.hud-profile'}",
            f"--window-size={int(self.cfg['width'])},{int(self.cfg['height'])}",
            "--no-first-run", "--no-default-browser-check", "--disable-extensions",
        ]
        if self.cfg["fullscreen"]:
            args.append("--start-fullscreen")
        elif self.cfg["maximized"]:
            args.append("--start-maximized")
        try:
            self._edge = subprocess.Popen(args)
            return True
        except OSError as exc:
            log.warning("Edge app mode failed: %r", exc)
            return False

    def _run_edge(self, start_hidden: bool) -> bool:
        if not self._edge_path():
            return False
        self.kind = "edge"
        if not start_hidden and not self._launch_edge():
            self.kind = ""
            return False
        self._on_ready()
        self._quit.wait()  # closing the Edge window does not stop Jarvis (tray > Quit does)
        return True
