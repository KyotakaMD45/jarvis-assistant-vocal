"""Computer control: lock, sleep, shut down, restart, screenshot, brightness, battery.

Sleep, shut down and restart always ask for a spoken "oui" first, and shutdown/restart wait
15 seconds so they can still be cancelled ("annule l'extinction").
"""
from __future__ import annotations

from datetime import datetime

from jarvis.commands import Command, CommandContext
from jarvis.commands._words import COMPUTER, DO, DOWN, PUT, UP
from jarvis.system_stats import SystemStats
from jarvis.textnorm import simple, words_to_number
from jarvis.winctl import (cancel_shutdown, get_brightness, known_folder, lock_workstation, set_brightness,
                           shutdown, sleep_computer)

CONFIRM = {
    "sleep": "Voulez-vous vraiment mettre l'ordinateur en veille ? Répondez oui ou non.",
    "shutdown": "Voulez-vous vraiment éteindre l'ordinateur ? Répondez oui ou non.",
    "restart": "Voulez-vous vraiment redémarrer l'ordinateur ? Répondez oui ou non.",
}


def _screenshot() -> str:
    from PIL import ImageGrab

    folder = known_folder("pictures") / "Jarvis"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"capture_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
    ImageGrab.grab(all_screens=True).save(path)
    return str(path)


def system(ctx: CommandContext, args: dict) -> str:
    action = args["action"]
    if action == "lock":
        lock_workstation()
        return "Session verrouillée."
    if action == "sleep":
        if ctx.say:
            ctx.say("Mise en veille.")
        sleep_computer()
        return None
    if action in ("shutdown", "restart"):
        shutdown(action, 15)
        verb = "s'éteindra" if action == "shutdown" else "redémarrera"
        return f"L'ordinateur {verb} dans 15 secondes. Dites : annule l'extinction, pour l'arrêter."
    if action == "cancel_shutdown":
        return "Extinction annulée." if cancel_shutdown() else "Aucune extinction n'était prévue."
    if action == "screenshot":
        _screenshot()
        return "Capture d'écran enregistrée dans Images, dossier Jarvis."
    if action == "battery":
        stats = SystemStats().read()
        if stats["battery"] is None:
            return "Cet ordinateur n'a pas de batterie, il est sur secteur."
        state = "en charge" if stats["charging"] else "sur batterie"
        return f"La batterie est à {stats['battery']} pour cent, {state}."
    if "brightness" in action:
        try:
            current = get_brightness()
        except Exception:  # noqa: BLE001
            return "Je ne peux pas régler la luminosité de cet écran."
        if action == "brightness_up":
            value = set_brightness(current + 15)
        elif action == "brightness_down":
            value = set_brightness(current - 15)
        else:
            level = args.get("level")
            level = level if isinstance(level, (int, float)) else words_to_number(
                simple(str(level or "")).replace("%", "").replace("pour cent", "").strip())
            if level is None:
                return "À quel niveau ? Dites par exemple : luminosité à soixante-dix pour cent."
            value = set_brightness(int(level))
        return f"Luminosité à {value} pour cent."
    return "Je ne connais pas cette action."


COMMANDS = [
    Command(
        name="system_control",
        description="Control the computer: lock the session, sleep, shutdown, restart, cancel_shutdown, "
                    "screenshot, battery level, brightness_up, brightness_down, set_brightness (level 5-100).",
        run=system,
        confirm=lambda args: CONFIRM.get(args.get("action")),
        patterns=[
            (r"^(?:verrouille|verrouillez|verrouiller|bloque|bloquez)\s+(?:" + COMPUTER + r"|la session|l'ecran|ma session)", {"action": "lock"}),
            (r"^(?:" + PUT + r"\s+)?(?:" + COMPUTER + r"\s+)?en veille$", {"action": "sleep"}),
            (r"^(?:eteins|eteint|etein|eteinds|eteignez|eteindre|arrete|arretez)\s+" + COMPUTER, {"action": "shutdown"}),
            (r"^(?:redemarre|redemarrez|redemarrer|relance|relancez)\s+" + COMPUTER, {"action": "restart"}),
            (r"^(?:annule|annulez|stoppe)\s+(?:l'extinction|l'arret|le redemarrage|l extinction)", {"action": "cancel_shutdown"}),
            (r"(?:^|\b" + DO + r"\s+)(?:une\s+)?(?:capture|copie)\s+(?:d'ecran|de l'ecran|d ecran|ecran)|^screenshot$", {"action": "screenshot"}),
            (r"^(?:quel est |quelle est |c'est quoi |donne moi |dis moi )?(?:le |la |l')?(?:niveau de (?:la )?batterie|etat de la batterie|batterie|autonomie|charge de la batterie)$", {"action": "battery"}),
            (r"\bcombien (?:de|il reste de|me reste[ -]t[ -]il de) batterie\b", {"action": "battery"}),
            (r"^" + UP + r"\s+(?:la\s+)?luminosite", {"action": "brightness_up"}),
            (r"^" + DOWN + r"\s+(?:la\s+)?luminosite", {"action": "brightness_down"}),
            (r"^(?:" + PUT + r"\s+)?(?:la\s+)?luminosite\s+(?:a|au|sur)\s+(?P<level>.+)$", {"action": "set_brightness"}),
        ],
        parameters={
            "action": {"type": "string", "enum": ["lock", "sleep", "shutdown", "restart", "cancel_shutdown", "screenshot",
                                                   "battery", "brightness_up", "brightness_down", "set_brightness"]},
            "level": {"type": "integer", "description": "Brightness level for set_brightness"},
        },
        required=["action"],
        priority=70,
    ),
]
