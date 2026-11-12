"""System tray icon (notification area): Jarvis keeps running when the window/terminal is closed."""
from __future__ import annotations

import threading
from collections.abc import Callable

from jarvis.logger import get_logger

log = get_logger(__name__)


def _make_icon(size: int = 64, paused: bool = False):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (120, 140, 150, 255) if paused else (0, 229, 255, 255)
    d.ellipse((2, 2, size - 3, size - 3), fill=(2, 10, 20, 255), outline=color, width=3)
    d.arc((12, 12, size - 13, size - 13), 200, 340, fill=color, width=4)
    d.arc((12, 12, size - 13, size - 13), 20, 160, fill=color, width=4)
    r = size // 7
    c = size // 2
    d.ellipse((c - r, c - r, c + r, c + r), fill=(200, 250, 255, 255) if not paused else color)
    return img


class Tray:
    def __init__(self, on_show: Callable[[], None], on_toggle_listening: Callable[[], None],
                 is_listening: Callable[[], bool], on_restart: Callable[[], None], on_quit: Callable[[], None],
                 has_hud: bool = True):
        self.on_show = on_show
        self.on_toggle_listening = on_toggle_listening
        self.is_listening = is_listening
        self.on_restart = on_restart
        self.on_quit = on_quit
        self.has_hud = has_hud
        self.icon = None

    def start(self) -> bool:
        try:
            import pystray
        except Exception as exc:  # noqa: BLE001
            log.error("Tray icon unavailable: %r", exc)
            return False

        def safe(fn):
            def wrapper(icon, item):  # pystray calls with (icon, item)
                try:
                    fn()
                except Exception:  # noqa: BLE001
                    log.exception("Tray action failed")
                self.refresh()
            return wrapper

        items = []
        if self.has_hud:
            items.append(pystray.MenuItem("Afficher Knull", safe(self.on_show), default=True))
        items += [
            pystray.MenuItem("Écoute active", safe(self.on_toggle_listening), checked=lambda item: self.is_listening()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Redémarrer", safe(self.on_restart)),
            pystray.MenuItem("Quitter", safe(self.on_quit)),
        ]
        self.icon = pystray.Icon("jarvis", _make_icon(), "Knull - à l'écoute", menu=pystray.Menu(*items))
        threading.Thread(target=self.icon.run, name="tray", daemon=True).start()
        log.info("Tray icon started")
        return True

    def refresh(self) -> None:
        if self.icon is None:
            return
        listening = self.is_listening()
        try:
            self.icon.icon = _make_icon(paused=not listening)
            self.icon.title = "Knull - à l'écoute" if listening else "Knull - micro en pause"
            self.icon.update_menu()
        except Exception:  # noqa: BLE001
            pass

    def notify(self, title: str, text: str) -> None:
        if self.icon is not None:
            try:
                self.icon.notify(text[:250], title[:60])
            except Exception:  # noqa: BLE001
                log.debug("Tray notification failed", exc_info=True)

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:  # noqa: BLE001
                pass
