"""See and act on application windows like a person would, through Windows UI Automation
(the accessibility layer screen readers use): list the visible buttons/fields/rows, find one by
its name (tolerant to speech-recognition spelling), click it, type into it.

Web-based apps (WhatsApp, Teams, browsers) only expose their content while they are in the
foreground, so the window is brought to the front first.
"""
from __future__ import annotations

import difflib
import re
import time
import unicodedata

from jarvis import pcctl
from jarvis.logger import get_logger

log = get_logger(__name__)

INTERACTIVE = {"ButtonControl", "EditControl", "ListItemControl", "DataItemControl", "MenuItemControl",
               "HyperlinkControl", "TabItemControl", "CheckBoxControl", "ComboBoxControl", "RadioButtonControl",
               "TreeItemControl", "SplitButtonControl"}


def _auto():
    import uiautomation as auto  # imported lazily (COM initialisation, ~0.3 s)

    return auto


# ---------------------------------------------------------------------------------------
# Fuzzy names ("Benemaro" / "Bénémarou" / "Benimaru 💁 ❤️")
# ---------------------------------------------------------------------------------------
def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text).split())


def _skeleton(text: str) -> str:
    s = fold(text).replace(" ", "")
    s = s.replace("ph", "f").replace("qu", "k").replace("c", "k").replace("y", "i")
    s = re.sub(r"(.)\1+", r"\1", s)
    return re.sub(r"[aeiou]", "", s)


def name_score(wanted: str, candidate: str) -> float:
    """0..1: how well a spoken name matches a name on screen (start of the candidate counts)."""
    w, c = fold(wanted), fold(candidate)
    if not w or not c:
        return 0.0
    if w == c or c.startswith(w + " ") or c == w:
        return 1.0
    words = c.split()
    best = 0.0
    n = len(w.split())
    for size in range(max(1, n - 1), n + 2):  # compare with the first words of the candidate
        part = " ".join(words[:size])
        raw = difflib.SequenceMatcher(None, w, part).ratio()
        sk1, sk2 = _skeleton(w), _skeleton(part)
        sk = difflib.SequenceMatcher(None, sk1, sk2).ratio() if sk1 and sk2 else 0.0
        best = max(best, 0.55 * raw + 0.45 * sk)
    if w in c:
        best = max(best, 0.85)
    return best


# ---------------------------------------------------------------------------------------
# Windows and elements
# ---------------------------------------------------------------------------------------
def find_window(title_part: str = "", process: str = ""):
    from jarvis.winctl import list_windows

    for hwnd, title, proc in list_windows():
        if process and process.lower() in proc.lower():
            return hwnd
        if title_part and title_part.lower() == title.strip().lower():
            return hwnd
    return None


def bring_front(hwnd) -> bool:
    return pcctl.focus(hwnd)


def elements(hwnd, max_nodes: int = 2500, max_seconds: float = 3.0, kinds=INTERACTIVE) -> list:
    """Visible elements of a window: list of (control, type, name)."""
    auto = _auto()
    root = auto.ControlFromHandle(hwnd)
    out, count, started = [], 0, time.monotonic()

    def walk(ctrl, depth):
        nonlocal count
        if depth > 45 or count > max_nodes or time.monotonic() - started > max_seconds:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:  # noqa: BLE001 - elements can vanish while walking
            return
        for ch in children:
            count += 1
            try:
                ct = ch.ControlTypeName
                if ct in kinds:
                    out.append((ch, ct, (ch.Name or "").strip()))
            except Exception:  # noqa: BLE001
                continue
            walk(ch, depth + 1)

    walk(root, 0)
    return out


def wait_for(hwnd, predicate, timeout: float = 6.0, kinds=INTERACTIVE):
    """Re-read the window until predicate(elements) returns something (web apps load lazily)."""
    deadline = time.monotonic() + timeout
    while True:
        found = predicate(elements(hwnd, kinds=kinds))
        if found or time.monotonic() > deadline:
            return found
        time.sleep(0.35)


def best_match(items: list, wanted: str, kinds: set | None = None, minimum: float = 0.6):
    """(control, score, name) of the element whose name best matches `wanted`, or None."""
    scored = []
    for ctrl, ct, name in items:
        if kinds and ct not in kinds:
            continue
        if not name:
            continue
        scored.append((name_score(wanted, name), ctrl, name))
    if not scored:
        return None
    scored.sort(key=lambda x: -x[0])
    score, ctrl, name = scored[0]
    return (ctrl, score, name) if score >= minimum else None


def click(ctrl) -> bool:
    """Activate an element: Invoke / Select / default action, else a real mouse click on it."""
    for getter, action in (("GetInvokePattern", "Invoke"), ("GetSelectionItemPattern", "Select"),
                           ("GetLegacyIAccessiblePattern", "DoDefaultAction")):
        try:
            pattern = getattr(ctrl, getter)()
            if pattern:
                getattr(pattern, action)()
                return True
        except Exception:  # noqa: BLE001
            continue
    try:
        ctrl.Click(simulateMove=False)
        return True
    except Exception:  # noqa: BLE001
        log.exception("Click failed")
        return False


def type_into(ctrl, text: str, replace: bool = True) -> bool:
    """Put text in a field: focus it, (select all,) paste."""
    try:
        ctrl.SetFocus()
    except Exception:  # noqa: BLE001
        try:
            ctrl.Click(simulateMove=False)
        except Exception:  # noqa: BLE001
            return False
    time.sleep(0.15)
    if replace:
        pcctl.send_combo("ctrl+a")
    return pcctl.paste_text(text)


def value_of(ctrl) -> str:
    try:
        return ctrl.GetValuePattern().Value or ""
    except Exception:  # noqa: BLE001
        try:
            return ctrl.GetLegacyIAccessiblePattern().Value or ""
        except Exception:  # noqa: BLE001
            return ""


def describe(hwnd, limit: int = 70) -> str:
    """Short text description of what is on screen, for the AI ("button: Envoyer; field: ...")."""
    labels = {"ButtonControl": "bouton", "EditControl": "champ", "ListItemControl": "élément", "DataItemControl": "ligne",
              "MenuItemControl": "menu", "HyperlinkControl": "lien", "TabItemControl": "onglet", "CheckBoxControl": "case",
              "ComboBoxControl": "liste", "RadioButtonControl": "option", "TreeItemControl": "élément",
              "SplitButtonControl": "bouton"}
    seen, parts = set(), []
    for _ctrl, ct, name in elements(hwnd):
        if not name or len(name) < 2:
            continue
        short = re.sub(r"\s+", " ", name)[:50]
        key = (ct, short)
        if key in seen:
            continue
        seen.add(key)
        parts.append(f"{labels.get(ct, ct)}: {short}")
        if len(parts) >= limit:
            break
    title = pcctl.window_info(hwnd)[1]
    return f"Fenêtre « {title[:60]} » — " + "; ".join(parts)
