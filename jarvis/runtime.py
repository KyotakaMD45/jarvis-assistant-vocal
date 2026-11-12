"""Background runtime: assistant + HUD window + tray icon + single instance + restart.

Threads: the HUD window owns the main thread (WebView2 requires it); the assistant, the
tray icon, the reminders and the HUD server each run in their own background thread.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from jarvis.logger import get_logger
from jarvis.paths import ROOT

log = get_logger(__name__)


def background_python() -> str:
    """pythonw.exe (no console window) next to the current interpreter, if present."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate) if candidate.exists() else str(exe)


class Runtime:
    def __init__(self, cfg: dict, warnings: list[str], use_hud: bool, instance, start_hidden: bool = False):
        from jarvis.brain import Brain
        from jarvis.reminders import ReminderService
        from jarvis.tray import Tray
        from jarvis.ui import Ui
        from jarvis.voice import VoiceAssistant

        self.cfg = cfg
        self.use_hud = use_hud
        self.start_hidden = start_hidden
        self.quit_event = threading.Event()
        self.restart_requested = False
        self.instance = instance  # InstanceLock, already acquired
        self.server = None
        self.window = None
        if use_hud:
            from jarvis.hud_server import HudServer

            hud = cfg["hud"]
            self.server = HudServer({"fps": hud["fps"], "low_power": hud["low_power"], "assistant_name": cfg["assistant_name"]})
        ui = Ui(self.server.publish) if self.server else Ui()
        self.assistant = VoiceAssistant(cfg, Brain(cfg), warnings, ui=ui)
        self.tray = Tray(on_show=self.show_hud, on_toggle_listening=self.assistant.toggle_listening,
                         is_listening=lambda: self.assistant.listening_enabled,
                         on_restart=self.restart, on_quit=self.quit, has_hud=use_hud)
        self.reminders = ReminderService(on_due=self.assistant.announce)
        a = self.assistant
        a.reminders = self.reminders
        a.notify = self.tray.notify
        a.on_show_hud = self.show_hud
        a.on_hide_hud = self.hide_hud
        a.on_minimize_hud = self.minimize_hud
        a.on_quit = self.quit
        a.on_restart = self.restart
        a.on_listening_changed = self.tray.refresh
        if self.server is not None:
            self.server.on_command = a.submit_text
            self.server.on_action = a.handle_action

    # -- actions (any thread) ----------------------------------------------------------------
    def show_hud(self) -> None:
        if self.window is not None:
            self.window.show()

    def minimize_hud(self) -> None:
        if self.window is not None:
            self.window.minimize()

    def hide_hud(self) -> None:
        if self.window is not None:
            self.window.hide()

    def quit(self) -> None:
        if self.quit_event.is_set():
            return
        log.info("Quit requested")
        self.quit_event.set()
        self.assistant.request_stop()
        if self.window is not None:
            self.window.quit()

    def restart(self) -> None:
        self.restart_requested = True
        self.quit()

    # -- lifecycle -------------------------------------------------------------------------
    def run(self) -> int:
        self.instance.serve({"show": self.show_hud, "quit": self.quit, "restart": self.restart})
        self.reminders.start()
        self.tray.start()
        worker = threading.Thread(target=self._assistant_main, name="assistant", daemon=True)
        started = threading.Event()

        def start_assistant() -> None:
            # Started once the window is on screen: loading models while WebView2 starts slows both.
            if not started.is_set():
                started.set()
                worker.start()

        if self.use_hud:
            from jarvis.hud_window import HudWindow

            url = self.server.start()
            self.server.start_stats(2.0)
            self.window = HudWindow(url, self.cfg["hud"])
            self.window.run(on_ready=start_assistant, start_hidden=self.start_hidden)  # blocks until quit
        else:
            start_assistant()
            try:
                while not self.quit_event.wait(0.5):
                    pass
            except KeyboardInterrupt:
                self.quit()
        self.quit()
        self._shutdown(worker if started.is_set() else None)
        if self.restart_requested:
            self._spawn_new_instance()
        return 0

    def _assistant_main(self) -> None:
        try:
            self.assistant.run()
        except Exception:  # noqa: BLE001
            log.exception("Voice assistant crashed")
        finally:
            self.quit()

    def _shutdown(self, worker: threading.Thread | None) -> None:
        if worker is not None:
            worker.join(5)
        self.reminders.stop()
        self.tray.stop()
        self.assistant.close()
        if self.server is not None:
            self.server.stop()
        self.instance.release()
        log.info("Shutdown complete")

    def _spawn_new_instance(self) -> None:
        args = [background_python(), "-m", "jarvis", "--wait-pid", str(os.getpid())]
        args += [a for a in sys.argv[1:] if a in ("--no-hud", "--hidden")]
        log.info("Restarting: %s", args)
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, cwd=str(ROOT), creationflags=flags, close_fds=True)
