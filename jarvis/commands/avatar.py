"""Avatar gaze: "regarde à gauche / à droite / en haut / en bas / regarde-moi"."""
from __future__ import annotations

from jarvis.commands import Command, CommandContext

DIRECTIONS = {
    "gauche": "left", "a gauche": "left", "left": "left",
    "droite": "right", "a droite": "right", "right": "right",
    "haut": "up", "en haut": "up", "le haut": "up", "le plafond": "up", "up": "up",
    "bas": "down", "en bas": "down", "le bas": "down", "le sol": "down", "par terre": "down", "down": "down",
    "moi": "center", "devant": "center", "devant toi": "center", "en face": "center", "face": "center",
    "tout droit": "center", "center": "center",
}
SPOKEN = {"left": "Je regarde à gauche.", "right": "Je regarde à droite.", "up": "Je regarde en haut.",
          "down": "Je regarde en bas.", "center": "Je te regarde."}


def look(ctx: CommandContext, args: dict) -> str:
    raw = (args.get("direction") or "center").strip().lower()
    direction = DIRECTIONS.get(raw, raw if raw in SPOKEN else "center")
    if ctx.assistant is not None:
        ctx.assistant.avatar_look(direction)
    return SPOKEN[direction]


_DIR = r"(?P<direction>gauche|droite|haut|bas|devant toi|devant|moi|en face|face|tout droit|le haut|le bas|le plafond|le sol|par terre)"

COMMANDS = [
    Command(
        name="avatar_look",
        description="Turn the avatar's head to look left, right, up, down, or back at the user (center).",
        run=look,
        patterns=[
            r"^(?:regarde|regardez|regard|tourne(?: la| ta)? tete|tourne[ -]toi|tourne[ -]la tete)\s+(?:vers\s+|a\s+|en\s+|sur\s+)?(?:la\s+|ta\s+)?" + _DIR + r"$",
            (r"^(?:regarde[ -]moi|regardez[ -]moi|regarde[ -]nous|tourne[ -]toi vers moi)$", {"direction": "center"}),
        ],
        parameters={"direction": {"type": "string", "enum": ["left", "right", "up", "down", "center"]}},
        required=["direction"],
        priority=85,
    ),
]
