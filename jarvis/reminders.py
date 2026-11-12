"""Reminders and timers: French time parsing, persistence (reminders.json), background scheduler."""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta

from jarvis.logger import get_logger
from jarvis.paths import ROOT
from jarvis.textnorm import NUMBER_WORDS, fold, words_to_number

log = get_logger(__name__)

STORE = ROOT / "reminders.json"

_WORD = "|".join(sorted(NUMBER_WORDS - {"et"}, key=len, reverse=True))
NUM = rf"(?:\d+|(?:{_WORD})(?:[\s-]+(?:et[\s-]+)?(?:{_WORD}))*)"
_UNIT = r"(?P<unit>secondes?|sec|minutes?|mins?|heures?|h)\b"

_DELAY = re.compile(
    r"\b(?:dans|pendant|pour|de)?\s*(?:"
    r"(?P<quarter>un quart d'heure|un quart d heure)|(?P<halfhour>une demi[- ]heure)|"
    rf"(?P<n>{NUM}|une?)\s*{_UNIT}(?:\s+et\s+(?:(?P<half>demie?)|(?P<quart>quart)|(?P<n2>{NUM})\s*(?:minutes?|mins?)?))?"
    r")"
)
_AT = re.compile(
    rf"\b(?P<day>demain\s+|apres[- ]demain\s+|ce soir\s+|ce matin\s+)?(?:a|vers|pour)\s+(?:"
    rf"(?P<noon>midi|minuit)|(?P<h>{NUM})\s*(?:heures?|h)(?:\s*(?P<m>{NUM}|et quart|et demie?|moins le quart))?)"
    r"(?:\s+du matin|\s+du soir|\s+de l'apres[- ]midi)?"
)


def _num(text: str | None) -> int | None:
    if not text:
        return None
    return 1 if text.strip() in ("un", "une") else words_to_number(text)


def parse_delay(folded: str) -> tuple[timedelta, tuple[int, int]] | None:
    """Find '10 minutes', 'dans une heure et demie', 'un quart d'heure'... in folded text."""
    for m in _DELAY.finditer(folded):
        if m.group("quarter"):
            return timedelta(minutes=15), m.span()
        if m.group("halfhour"):
            return timedelta(minutes=30), m.span()
        n = _num(m.group("n"))
        if n is None:
            continue
        unit = m.group("unit")
        if unit.startswith("s"):
            delta = timedelta(seconds=n)
        elif unit.startswith("m"):
            delta = timedelta(minutes=n)
        else:
            delta = timedelta(hours=n)
            if m.group("half"):
                delta += timedelta(minutes=30)
            elif m.group("quart"):
                delta += timedelta(minutes=15)
            elif m.group("n2"):
                delta += timedelta(minutes=_num(m.group("n2")) or 0)
        return delta, m.span()
    return None


def parse_clock(folded: str, now: datetime | None = None) -> tuple[datetime, tuple[int, int]] | None:
    """Find 'a 18 heures 30', 'a dix huit heures trente', 'demain a 9 h', 'a midi'..."""
    now = now or datetime.now()
    m = _AT.search(folded)
    if not m:
        return None
    if m.group("noon"):
        hour, minute = (12, 0) if m.group("noon") == "midi" else (0, 0)
    else:
        hour = _num(m.group("h"))
        if hour is None or hour > 23:
            return None
        minute = 0
        extra = (m.group("m") or "").strip()
        if extra.startswith("et quart"):
            minute = 15
        elif extra.startswith("et demi"):
            minute = 30
        elif extra == "moins le quart":
            hour, minute = (hour - 1) % 24, 45
        elif extra:
            minute = _num(extra) or 0
        said = m.group(0)
        if hour < 12 and ("du soir" in said or "apres" in said or (m.group("day") or "").startswith("ce soir")):
            hour += 12
    if minute > 59:
        return None
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    day = (m.group("day") or "").strip()
    if day == "demain":
        due += timedelta(days=1)
    elif day.startswith("apres"):
        due += timedelta(days=2)
    elif due <= now:
        due += timedelta(days=1)
    return due, m.span()


def parse_reminder(text: str, now: datetime | None = None) -> tuple[datetime, str] | None:
    """'de sortir le gâteau dans 10 minutes' -> (due, 'sortir le gâteau')."""
    now = now or datetime.now()
    original = text.strip()
    folded = fold(original)
    found = parse_clock(folded, now)
    if found:
        due, span = found
    else:
        delay = parse_delay(folded)
        if not delay:
            return None
        due, span = now + delay[0], delay[1]
    what = (original[:span[0]] + " " + original[span[1]:]).strip()
    what = re.sub(r"^(?:de |d'|d’|que |qu'|qu’|pour |dans )", "", what, flags=re.IGNORECASE).strip(" ,.")
    what = re.sub(r"\s+(?:de|d'|que|dans)$", "", what).strip()
    return due, what


def speak_due(due: datetime, now: datetime | None = None) -> str:
    from jarvis.commands.time_date import spoken_time

    now = now or datetime.now()
    delta = due - now
    if delta < timedelta(minutes=60):
        minutes = round(delta.total_seconds() / 60)
        if minutes < 1:
            seconds = max(1, round(delta.total_seconds()))
            return f"dans {seconds} secondes"
        return "dans une minute" if minutes == 1 else f"dans {minutes} minutes"
    day = "demain " if due.date() == (now + timedelta(days=1)).date() else ""
    return f"{day}à {spoken_time(due)}"


class ReminderService:
    def __init__(self, on_due: Callable[[str], None], path=STORE):
        self.on_due = on_due
        self.path = path
        self._items: list[dict] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [i for i in data if isinstance(i, dict) and "due" in i and "what" in i]
        except FileNotFoundError:
            self._items = []
        except (OSError, ValueError) as exc:
            log.error("reminders.json unreadable (%r), starting empty", exc)
            self._items = []

    def _save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._items, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.path)
        except OSError as exc:
            log.error("Could not save reminders: %r", exc)

    def add(self, what: str, due: datetime, kind: str = "reminder") -> dict:
        item = {"id": uuid.uuid4().hex[:8], "what": what, "due": due.isoformat(timespec="seconds"), "kind": kind}
        with self._lock:
            self._items.append(item)
            self._items.sort(key=lambda i: i["due"])
            self._save()
        log.info("Reminder added: %s at %s", what, item["due"])
        return item

    def pending(self) -> list[dict]:
        with self._lock:
            return list(self._items)

    def clear(self) -> int:
        with self._lock:
            count = len(self._items)
            self._items = []
            self._save()
        return count

    def start(self) -> None:
        threading.Thread(target=self._loop, name="reminders", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now()
            due_items = []
            with self._lock:
                for item in list(self._items):
                    try:
                        due = datetime.fromisoformat(item["due"])
                    except ValueError:
                        self._items.remove(item)
                        continue
                    if due <= now:
                        self._items.remove(item)
                        due_items.append((item, now - due))
                if due_items:
                    self._save()
            for item, late in due_items:
                what = item["what"]
                if item.get("kind") == "timer":
                    text = f"Le minuteur est terminé{' : ' + what if what else ''}."
                elif late > timedelta(minutes=2):
                    text = f"Rappel manqué pendant que j'étais éteint : {what}."
                else:
                    text = f"Rappel : {what}."
                try:
                    self.on_due(text)
                except Exception:  # noqa: BLE001
                    log.exception("Reminder callback failed")
            time.sleep(1)
