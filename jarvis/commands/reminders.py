"""Reminders and timers ("rappelle-moi dans 10 minutes de...", "minuteur de 5 minutes")."""
from __future__ import annotations

from datetime import datetime, timedelta

from jarvis.commands import Command, CommandContext
from jarvis.commands._words import PUT
from jarvis.reminders import parse_delay, parse_reminder, speak_due
from jarvis.textnorm import fold


def _service(ctx: CommandContext):
    if ctx.reminders is None:
        raise RuntimeError("reminder service not running")
    return ctx.reminders


def set_reminder(ctx: CommandContext, args: dict) -> str:
    service = _service(ctx)
    if "in_minutes" in args or "at_time" in args:  # called by the AI with structured arguments
        what = args.get("what") or "rappel"
        if "at_time" in args:
            hour, _, minute = str(args["at_time"]).partition(":")
            now = datetime.now()
            due = now.replace(hour=int(hour) % 24, minute=int(minute or 0) % 60, second=0, microsecond=0)
            if due <= now:
                due += timedelta(days=1)
        else:
            due = datetime.now() + timedelta(minutes=float(args["in_minutes"]))
    else:
        parsed = parse_reminder(args.get("rest", ""))
        if not parsed:
            return "Quand dois-je vous le rappeler ? Dites par exemple : rappelle-moi dans dix minutes de sortir le gâteau."
        due, what = parsed
        what = what or "rappel"
    service.add(what, due)
    return f"C'est noté, je vous rappellerai {speak_due(due)} : {what}."


def set_timer(ctx: CommandContext, args: dict) -> str:
    service = _service(ctx)
    if "minutes" in args:
        delta = timedelta(minutes=float(args["minutes"]))
    else:
        found = parse_delay(fold(args.get("rest", "")))
        if not found:
            return "De combien de temps ? Dites par exemple : minuteur de cinq minutes."
        delta = found[0]
    due = datetime.now() + delta
    service.add(args.get("label", ""), due, kind="timer")
    return f"Minuteur lancé, il sonnera {speak_due(due)}."


def list_reminders(ctx: CommandContext, args: dict) -> str:
    items = _service(ctx).pending()
    if not items:
        return "Vous n'avez aucun rappel en attente."
    parts = []
    for item in items[:5]:
        due = datetime.fromisoformat(item["due"])
        label = "minuteur" if item.get("kind") == "timer" else item["what"]
        parts.append(f"{label}, {speak_due(due)}")
    more = f", et {len(items) - 5} autres" if len(items) > 5 else ""
    return f"Vous avez {len(items)} rappel{'s' if len(items) > 1 else ''} : " + " ; ".join(parts) + more + "."


def clear_reminders(ctx: CommandContext, args: dict) -> str:
    count = _service(ctx).clear()
    return "Il n'y avait aucun rappel." if count == 0 else f"J'ai supprimé {count} rappel{'s' if count > 1 else ''}."


_RAPPEL = r"(?:r?appels?|r?appelles?|minuteurs?|timers?)"

COMMANDS = [
    Command(
        name="set_timer",
        description="Start a countdown timer.",
        run=set_timer,
        patterns=[
            r"^(?:" + PUT + r"|lance|lancez|demarre|demarrez|programme|regle)\s+(?:moi\s+)?(?:un\s+)?(?:minuteur|timer|chrono|compte a rebours)\s+(?:de\s+|pour\s+|sur\s+)?(?P<rest>.+)$",
            r"^(?:minuteur|timer)\s+(?:de\s+|pour\s+)?(?P<rest>.+)$",
        ],
        parameters={"minutes": {"type": "number", "description": "Duration in minutes"},
                    "label": {"type": "string", "description": "Optional label"}},
        required=["minutes"],
        priority=60,
    ),
    Command(
        name="set_reminder",
        description="Remind the user of something later: after a delay (in_minutes) or at a time of day (at_time 'HH:MM').",
        run=set_reminder,
        patterns=[
            r"^(?:rappelle|rappelez|rappeler|rapelle)[ -]?(?:moi|nous)?\s+(?P<rest>.+)$",
            r"^(?:fais|fait|faites)[ -]moi penser\s+(?P<rest>.+)$",
            r"^(?:n'oublie pas de me rappeler|noublie pas de me rappeler)\s+(?P<rest>.+)$",
        ],
        parameters={"what": {"type": "string", "description": "What to remind, in French"},
                    "in_minutes": {"type": "number", "description": "Delay in minutes from now"},
                    "at_time": {"type": "string", "description": "Time of day HH:MM (24h)"}},
        required=["what"],
        priority=60,
    ),
    Command(
        name="list_reminders",
        description="List the pending reminders and timers.",
        run=list_reminders,
        patterns=[r"^(?:quels? sont mes|liste mes|lis moi mes|lis mes|donne moi mes|j'ai des|ai je des|est ce que j'ai des|mes)\s+" + _RAPPEL],
        priority=60,
    ),
    Command(
        name="clear_reminders",
        description="Delete all pending reminders and timers.",
        run=clear_reminders,
        patterns=[r"^(?:annule|annulez|supprime|supprimez|efface|effacez|vide)\s+(?:tous\s+|toutes\s+)?(?:mes|les)\s+" + _RAPPEL],
        priority=60,
    ),
]
