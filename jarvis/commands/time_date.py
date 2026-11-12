"""Time and date, answered instantly without the AI."""
from __future__ import annotations

from datetime import datetime

from jarvis.commands import Command, CommandContext

DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]


def spoken_time(now: datetime) -> str:
    if now.hour == 0 and now.minute == 0:
        return "minuit"
    if now.hour == 12 and now.minute == 0:
        return "midi"
    hours = "une heure" if now.hour == 1 else f"{now.hour} heures"
    return hours if now.minute == 0 else f"{hours} {now.minute:02d}"


def spoken_date(day: datetime) -> str:
    number = "premier" if day.day == 1 else str(day.day)
    return f"{DAYS[day.weekday()]} {number} {MONTHS[day.month - 1]} {day.year}"


def tell_time(ctx: CommandContext, args: dict) -> str:
    return f"Il est {spoken_time(datetime.now())}."


def tell_date(ctx: CommandContext, args: dict) -> str:
    return f"Nous sommes {spoken_date(datetime.now())}."


COMMANDS = [
    Command(
        name="tell_time",
        ai_tool=False,
        description="Tell the current local time.",
        run=tell_time,
        patterns=[r"^(?:il est |tu as |t'as |donne moi |dis moi |c'est )?(?:quelle heure|l'heure|l heure)\b",
                  r"\bquelle heure (?:est[ -]il|il est)\b"],
        priority=30,
    ),
    Command(
        name="tell_date",
        ai_tool=False,
        description="Tell today's date and day of the week.",
        run=tell_date,
        patterns=[r"^(?:on est |nous sommes |c'est )?(?:quel jour|quelle date|la date|le combien)\b",
                  r"\b(?:quelle est la date|on est le combien|date d'aujourd'hui|quel jour on est|quel jour sommes)\b"],
        priority=30,
    ),
]
