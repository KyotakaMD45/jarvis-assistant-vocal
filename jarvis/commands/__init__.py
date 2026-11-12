"""Command registry.

Every module in this folder (except names starting with "_") is loaded automatically and
must define `COMMANDS = [Command(...), ...]`. See `_template.py` to add a new command.

A command can be triggered two ways:
1. instantly, when the sentence matches one of its French `patterns` (no AI call);
2. by the AI, which receives every command with `ai_tool=True` as a tool it may call
   when the sentence is phrased differently.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.logger import get_logger
from jarvis.textnorm import Utterance

log = get_logger(__name__)


class Unsure(Exception):
    """Raised by a command matched by its patterns when it cannot make sense of the arguments
    (e.g. no application with that name): the sentence is then given to the AI instead."""


@dataclass
class CommandContext:
    """What a command can use. Every field works in voice mode, text mode and tests."""

    cfg: dict
    say: Callable[[str], None]                      # speak/print a sentence right away
    ask_yes_no: Callable[[str], bool]               # ask a question, True if the user confirms
    assistant: Any = None                           # VoiceAssistant (None in text mode/tests)
    brain: Any = None
    reminders: Any = None                           # ReminderService
    notify: Callable[[str, str], None] = lambda title, text: None  # tray notification
    from_ai: bool = False                           # True when the AI called the command as a tool
    note: Callable[[str], None] = lambda text: None  # information for the AI's next step (not spoken)


@dataclass
class Command:
    name: str                                       # unique id, also the AI tool name
    description: str                                # English, read by the AI to pick the tool
    run: Callable[[CommandContext, dict], str | None]  # returns the sentence to say (or None)
    # Regexes tried on the folded sentence (lowercase, no accents). Named groups become arguments.
    # An entry can also be (regex, {"fixed": "arguments"}) to give a pattern fixed arguments.
    patterns: list = field(default_factory=list)
    parameters: dict = field(default_factory=dict)  # JSON schema properties of the arguments
    required: list[str] = field(default_factory=list)
    confirm: str | Callable[[dict], str | None] | None = None  # question asked first (risky actions)
    ai_tool: bool = True
    priority: int = 0                               # higher is tried first
    accept: Callable[[dict], bool] | None = None    # extra check after a pattern matched
    compiled: list = field(default_factory=list, repr=False)


@dataclass
class Match:
    command: Command
    args: dict


_registry: list[Command] = []


def load_commands() -> list[Command]:
    """Import every command module once (a broken module is logged and skipped)."""
    if _registry:
        return _registry
    seen: set[str] = set()
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:  # noqa: BLE001 - one bad file must not break Jarvis
            log.exception("Command module '%s' failed to load", info.name)
            continue
        for command in getattr(module, "COMMANDS", []):
            if command.name in seen:
                log.error("Duplicate command name '%s' in %s, skipped", command.name, info.name)
                continue
            seen.add(command.name)
            command.compiled = [
                (re.compile(p[0]), p[1]) if isinstance(p, tuple) else (re.compile(p), {})
                for p in command.patterns
            ]
            _registry.append(command)
    _registry.sort(key=lambda c: -c.priority)
    log.info("Loaded %d commands", len(_registry))
    return _registry


def match(text: str) -> Match | None:
    """Find the first command whose pattern matches the sentence.

    If nothing matches, retry without the first one or two words: the speech model sometimes
    turns a "Jarvis" said quickly into noise words ("gère vie bascule sur Claude").
    """
    found = _match_utterance(Utterance(text))
    if found is None:
        words = text.split()
        for skip in (1, 2):
            if len(words) - skip >= 2:
                found = _match_utterance(Utterance(" ".join(words[skip:])))
                if found is not None:
                    log.info("Matched %s after skipping %d leading word(s): %r", found.command.name, skip, text)
                    break
    return found


def _match_utterance(utt: Utterance) -> Match | None:
    if not utt.folded:
        return None
    for command in load_commands():
        for pattern, fixed in command.compiled:
            m = pattern.search(utt.folded)
            if not m:
                continue
            args = dict(fixed)
            args.update({k: utt.span(*m.span(k)) for k, v in m.groupdict().items() if v is not None})
            if command.accept is not None and not command.accept(args):
                continue
            return Match(command, args)
    return None


def get(name: str) -> Command | None:
    return next((c for c in load_commands() if c.name == name), None)


def tool_specs() -> list[dict]:
    """Neutral tool descriptions; each AI provider converts them to its own format."""
    specs = []
    for c in load_commands():
        if c.ai_tool:
            specs.append({
                "name": c.name,
                "description": c.description,
                "parameters": {"type": "object", "properties": c.parameters, "required": c.required,
                               "additionalProperties": False},
            })
    return specs


def validate_args(command: Command, args: Any) -> dict:
    """Check AI-provided arguments against the schema (types and required keys)."""
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    clean = {}
    for key, spec in command.parameters.items():
        if key not in args or args[key] is None:
            continue
        value = args[key]
        kind = spec.get("type")
        if kind == "string":
            if not isinstance(value, str):
                raise ValueError(f"'{key}' must be a string")
            if "enum" in spec and value not in spec["enum"]:
                raise ValueError(f"'{key}' must be one of {spec['enum']}")
            value = value.strip()[:300]
        elif kind in ("integer", "number"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"'{key}' must be a number")
        clean[key] = value
    missing = [k for k in command.required if k not in clean]
    if missing:
        raise ValueError(f"missing arguments: {missing}")
    return clean


def execute(command: Command, args: dict, ctx: CommandContext) -> str | None:
    """Run a command safely: confirmation for risky ones, and errors become a sentence."""
    question = command.confirm(args) if callable(command.confirm) else command.confirm
    if question and not ctx.ask_yes_no(question):
        return "D'accord, j'annule."
    try:
        log.info("Command %s %s", command.name, args)
        return command.run(ctx, args)
    except Unsure:
        if ctx.from_ai:
            raise RuntimeError("Unsure raised for an AI tool call")  # noqa: B904 - logged below
        raise
    except Exception:  # noqa: BLE001 - a failing command must never crash Jarvis
        log.exception("Command %s failed", command.name)
        return "Désolé, cette action a échoué. Les détails sont dans le journal."
