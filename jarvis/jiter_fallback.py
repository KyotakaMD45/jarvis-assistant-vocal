"""Pure-Python stand-in for the `jiter` library, used only if Windows blocks its DLL.

The Anthropic and OpenAI SDKs import `jiter` (a compiled, unsigned DLL) to parse partial JSON
while streaming. Windows Smart App Control sometimes refuses to load unsigned DLLs, which would
break every AI request. `ensure_jiter()` tries the real library first; if it cannot load, a
small pure-Python module with the same `from_json` function is registered instead.
"""
from __future__ import annotations

import json
import sys
import types

from jarvis.logger import get_logger

log = get_logger(__name__)


def _complete(text: str, trailing_strings: bool) -> str:
    """Close an incomplete JSON document: open strings, then arrays/objects."""
    stack: list[str] = []
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]" and stack:
            stack.pop()
    if in_string:
        text = text.rstrip("\\") + '"' if trailing_strings else text[: text.rfind('"')]
    text = text.rstrip()
    while text and text[-1] in ",:":
        text = text[:-1].rstrip() + (" null" if text[-1] == ":" else "")
        text = text.rstrip()
    return text + "".join(reversed(stack))


def from_json(json_data, *, allow_inf_nan=True, cache_mode=True, partial_mode=False,
              catch_duplicate_keys=False, float_mode="float"):
    text = json_data.decode("utf-8") if isinstance(json_data, (bytes, bytearray)) else str(json_data)
    try:
        return json.loads(text)
    except ValueError:
        if not partial_mode or partial_mode == "off":
            raise
    trailing = partial_mode == "trailing-strings"
    candidate = text
    for _ in range(64):  # drop an unfinished token at the end until the rest parses
        try:
            return json.loads(_complete(candidate, trailing))
        except ValueError:
            if not candidate:
                break
            candidate = candidate[:-1]
    return {}


def ensure_jiter() -> bool:
    """Return True if the real jiter works, False if the fallback was installed."""
    if "jiter" in sys.modules and getattr(sys.modules["jiter"], "__jarvis_fallback__", False):
        return False
    for _attempt in range(2):
        try:
            import jiter  # noqa: F401

            return True
        except (ImportError, OSError) as exc:
            last = exc
            sys.modules.pop("jiter", None)
            sys.modules.pop("jiter.jiter", None)
    module = types.ModuleType("jiter")
    module.__jarvis_fallback__ = True
    module.from_json = from_json
    module.cache_clear = lambda: None
    module.cache_usage = lambda: 0
    module.LosslessFloat = float
    module.__version__ = "0-fallback"
    sys.modules["jiter"] = module
    log.warning("jiter DLL blocked by Windows (%r): using the pure-Python fallback", last)
    return False
