"""Small persistent state that Jarvis changes itself (e.g. the AI chosen by voice), in state.json."""
from __future__ import annotations

import json

from jarvis.logger import get_logger
from jarvis.paths import ROOT

log = get_logger(__name__)
STATE_PATH = ROOT / "state.json"


def load_state() -> dict:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(**values) -> None:
    data = load_state()
    data.update(values)
    try:
        STATE_PATH.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except OSError as exc:
        log.error("Could not save state.json: %r", exc)
