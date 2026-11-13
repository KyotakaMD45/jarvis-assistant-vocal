"""Background runtime: assistant + HUD window + tray icon + single instance + restart.

Threads: the HUD window owns the main thread (WebView2 requires it); the assistant, the
tray icon, the reminders and the HUD server each run in their own background thread.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
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
        self.remote = None
        a.on_remote_pair = self.start_remote if self.server is not None else None
        a.on_remote_unpair = self.stop_remote
        if self.server is not None:
            self.server.on_command = a.submit_text
            self.server.on_action = a.handle_action

    # -- iPhone remote ------------------------------------------------------------------------
    def start_remote(self) -> str | None:
        """Start the phone server (if needed) and return the pairing URL."""
        from jarvis.remote import RemoteServer
        from jarvis.state import save_state

        if self.server is None:
            return None
        if self.remote is None:
            stt = self.assistant.listener

            def transcribe(data: bytes, name: str) -> str | None:
                t = getattr(stt, "transcriber", None)
                return t.transcribe_file(data, name) if t is not None and t.available() else None

            self.remote = RemoteServer(self.server, lambda text: self.assistant.submit_text(text, source="phone"),
                                       self.assistant.handle_action, transcribe=transcribe, status=self.phone_status)
            self.remote.start()
        save_state(remote_enabled=True)
        return self.remote.url

    def phone_status(self) -> dict:
        """What the phone page shows in its status panel (no secrets)."""
        from datetime import datetime

        import psutil

        a = self.assistant
        out = {"name": a.cfg.get("assistant_name", "Apex"), "listening": bool(a.listening_enabled),
               "ai": f"{a.brain.label} · {a.brain.model.split('/')[-1]}", "voice": a.speaker.cfg.get("voice", "")}
        if time.monotonic() < getattr(a.speaker, "_backup_until", 0):
            out["voice"] = a.speaker.cfg.get("voice_backup", "") + " (secours)"
        out["voice"] = out["voice"].replace("Neural", "").replace("Multilingual", "")
        try:
            out["cpu"] = round(psutil.cpu_percent(interval=0.2))
            out["ram"] = round(psutil.virtual_memory().percent)
            bat = psutil.sensors_battery()
            if bat is not None:
                out["battery"] = round(bat.percent)
                out["plugged"] = bool(bat.power_plugged)
        except Exception:  # noqa: BLE001
            pass
        reminders = []
        service = getattr(a, "reminders", None)
        for item in (service.pending() if service is not None else [])[:8]:
            try:
                due = datetime.fromisoformat(item["due"])
                reminders.append({"what": "Minuteur" if item.get("kind") == "timer" else item.get("what", ""),
                                  "due": due.strftime("%H:%M") if due.date() == datetime.now().date()
                                  else due.strftime("%d/%m %H:%M")})
            except (KeyError, ValueError):
                continue
        out["reminders"] = reminders
        return out

    def stop_remote(self) -> None:
        from jarvis.remote import remote_key
        from jarvis.state import save_state

        if self.remote is not None:
            self.remote.stop()
            self.remote = None
        remote_key(rotate=True)  # the old QR code / Siri shortcut stop working
        save_state(remote_enabled=False)

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
    def _start_watchdog(self) -> None:
        """A small separate process restarts Apex if it stops without being asked to."""
        from jarvis.watchdog import CLEAN_EXIT

        try:
            CLEAN_EXIT.unlink(missing_ok=True)
            flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen([background_python(), "-m", "jarvis.watchdog", str(os.getpid())], cwd=str(ROOT),
                             creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001 - the assistant must start even without its watchdog
            log.exception("Could not start the watchdog")

    def run(self) -> int:
        self._start_watchdog()
        try:
            from jarvis.state import load_state

            if self.server is not None and load_state().get("remote_enabled"):
                self.start_remote()
        except OSError:
            log.exception("iPhone remote could not start")
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
        from jarvis.watchdog import CLEAN_EXIT

        try:
            CLEAN_EXIT.write_text("ok")  # tells the watchdog this stop was asked for
        except OSError:
            pass
        log.info("Shutdown complete")

    def _spawn_new_instance(self) -> None:
        args = [background_python(), "-m", "jarvis", "--wait-pid", str(os.getpid())]
        args += [a for a in sys.argv[1:] if a in ("--no-hud", "--hidden")]
        log.info("Restarting: %s", args)
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, cwd=str(ROOT), creationflags=flags, close_fds=True)
