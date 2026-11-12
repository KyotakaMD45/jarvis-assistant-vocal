"""System volume: up, down, set to a level, mute, unmute, read."""
from __future__ import annotations

from jarvis.commands import Command, CommandContext
from jarvis.commands._words import DOWN, PUT, UP
from jarvis.textnorm import simple, words_to_number
from jarvis.winctl import get_volume, set_mute, set_volume

STEP = 10


def _level(text: str) -> int | None:
    key = simple(text).replace("%", "").replace("pour cent", "").replace("pourcent", "").strip()
    if key in ("fond", "a fond", "max", "maximum", "100", "cent"):
        return 100
    if key in ("moitie", "la moitie", "milieu"):
        return 50
    if key in ("minimum", "min", "tres bas"):
        return 5
    if key in ("zero", "0", "rien"):
        return 0
    return words_to_number(key)


def volume(ctx: CommandContext, args: dict) -> str:
    action = args.get("action", "set")
    current, muted = get_volume()
    if action == "up":
        return f"Volume à {set_volume(current + STEP)} pour cent."
    if action == "down":
        return f"Volume à {set_volume(current - STEP)} pour cent."
    if action == "mute":
        set_mute(True)
        return "Son coupé."
    if action == "unmute":
        set_mute(False)
        return f"Son rétabli, volume à {current} pour cent."
    if action == "get":
        return f"Le volume est à {current} pour cent{', mais le son est coupé' if muted else ''}."
    level = args.get("level")
    level = level if isinstance(level, (int, float)) else _level(str(level or ""))
    if level is None or not 0 <= level <= 100:
        return "À quel niveau ? Dites par exemple : volume à cinquante pour cent."
    if level == 0:
        set_mute(True)
        return "Son coupé."
    return f"Volume à {set_volume(int(level))} pour cent."


_VOL = r"(?:le\s+|la\s+|un peu le\s+|un peu\s+)?(?:son|volume|cent)"

COMMANDS = [
    Command(
        name="volume",
        description="Change the computer's sound volume: up, down, set (level 0-100), mute, unmute, get.",
        run=volume,
        patterns=[
            (r"^" + UP + r"\s+" + _VOL + r"\b", {"action": "up"}),
            (r"^(?:(?:un peu )?plus fort|parle plus fort|plus de son)$", {"action": "up"}),
            (r"^" + DOWN + r"\s+" + _VOL + r"\b", {"action": "down"}),
            (r"^(?:(?:un peu )?moins fort|parle moins fort|moins de son|plus bas)$", {"action": "down"}),
            (r"^(?:coupe|couple|couper|coupez|desactive)\s+" + _VOL + r"$", {"action": "mute"}),
            (r"^(?:mode silencieux|sourdine|" + PUT + r" en sourdine|mute|silence total)$", {"action": "mute"}),
            (r"^(?:remets|remet|reactive|retablis|retablit|active|rallume|remettre)\s+" + _VOL + r"$", {"action": "unmute"}),
            (r"^(?:quel est le volume|le volume est a combien|a combien est le (?:son|volume)|quel volume)", {"action": "get"}),
            (r"^(?:" + PUT + r"\s+)?(?:le\s+)?(?:son|volume)\s+(?:a|au|sur|en)\s+(?P<level>.+)$", {"action": "set"}),
            (r"^(?:" + PUT + r"\s+)?(?:le\s+)?(?:son|volume)\s+(?P<level>a fond|au maximum|au max|au minimum)$", {"action": "set"}),
        ],
        parameters={"action": {"type": "string", "enum": ["up", "down", "set", "mute", "unmute", "get"]},
                    "level": {"type": "integer", "description": "Target level 0-100 for action 'set'"}},
        required=["action"],
        priority=50,
    ),
]
