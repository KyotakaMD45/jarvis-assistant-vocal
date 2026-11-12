"""Small facade the voice loop uses to update the HUD. Without a HUD every call is a no-op."""
from __future__ import annotations

from collections.abc import Callable


class Ui:
    def __init__(self, publish: Callable[[str, dict | None], None] | None = None):
        self._publish = publish

    @property
    def enabled(self) -> bool:
        return self._publish is not None

    def _send(self, event: str, data: dict | None = None) -> None:
        if self._publish is not None:
            try:
                self._publish(event, data)
            except Exception:  # noqa: BLE001 - the HUD must never break the assistant
                pass

    def state(self, state: str) -> None:
        self._send("state", {"state": state})

    def level(self, value: float) -> None:
        self._send("level", {"value": round(value, 3)})

    def partial(self, text: str) -> None:
        self._send("partial", {"text": text})

    def log(self, role: str, text: str, entry_id: str | None = None, streaming: bool = False) -> None:
        self._send("log", {"role": role, "text": text, "id": entry_id, "streaming": streaming})

    def log_append(self, entry_id: str, text: str) -> None:
        self._send("log_append", {"id": entry_id, "text": text})

    def log_end(self, entry_id: str) -> None:
        self._send("log_end", {"id": entry_id})

    def status(self, **fields: str) -> None:
        self._send("status", fields)

    def look(self, direction: str) -> None:
        self._send("look", {"direction": direction})

    def boot(self, text: str, ok: bool = True) -> None:
        self._send("boot", {"text": text, "ok": ok})

    def ready(self) -> None:
        self._send("ready")
