"""Window management: minimize, maximize, restore, close, switch, desktop, snap left/right."""
from __future__ import annotations

from jarvis import pcctl
from jarvis.commands import Command, CommandContext

ACTIONS = ["minimize", "maximize", "restore", "close", "switch", "show_desktop", "snap_left", "snap_right", "task_view"]


def window(ctx: CommandContext, args: dict) -> str | None:
    action = args.get("action")
    if action == "show_desktop":
        pcctl.send_combo("win+d")
        return "Voici le bureau."
    if action == "task_view":
        pcctl.send_combo("win+tab")
        return ""
    if action == "switch":
        hwnd = pcctl.target_window()
        if hwnd:
            pcctl.focus(hwnd)
        pcctl.send_combo("alt+tab")
        return ""
    hwnd = pcctl.target_window()
    if not hwnd:
        return "Je ne trouve pas de fenêtre ouverte."
    _cls, title, _pid = pcctl.window_info(hwnd)
    name = title.split(" - ")[-1].strip() or "la fenêtre"
    if action == "minimize":
        pcctl.show_window(hwnd, pcctl.SW_MINIMIZE)
        return "Fenêtre réduite."
    if action == "maximize":
        pcctl.show_window(hwnd, pcctl.SW_MAXIMIZE)
        return "Fenêtre agrandie."
    if action == "restore":
        pcctl.show_window(hwnd, pcctl.SW_RESTORE)
        return "Fenêtre restaurée."
    if action == "close":
        pcctl.close(hwnd)
        return f"Je ferme {name}."
    if action in ("snap_left", "snap_right"):
        pcctl.focus(hwnd)
        pcctl.send_combo("win+left" if action == "snap_left" else "win+right")
        return ""
    return "Je ne connais pas cette action."


_WIN = r"(?:la fenetre|cette fenetre|la fenetre active|l'application|cette application)"
COMMANDS = [
    Command(
        name="window_control",
        description="Manage the window the user is working in: minimize, maximize, restore, close, switch (to the "
                    "next window), show_desktop, snap_left, snap_right (half screen), task_view.",
        run=window,
        patterns=[
            (r"^(?:reduis|reduit|reduire|minimise|minimiser|cache) " + _WIN + r"$", {"action": "minimize"}),
            (r"^(?:agrandis|agrandit|agrandir|maximise|maximiser) " + _WIN + r"$", {"action": "maximize"}),
            (r"^(?:restaure|restaurer) " + _WIN + r"$", {"action": "restore"}),
            (r"^(?:ferme|fermer|fermez|quitte) " + _WIN + r"$", {"action": "close"}),
            (r"^(?:change|changer|passe a la|bascule|basculer) (?:de |sur la |vers la )?fenetre(?: suivante)?$|^fenetre suivante$", {"action": "switch"}),
            (r"^(?:affiche|montre|montre-moi|va sur|retourne sur|reviens sur) (?:le|mon) bureau$|^(?:le )?bureau$", {"action": "show_desktop"}),
            (r"^(?:mets|met|place|deplace|colle) " + _WIN + r" (?:a|sur la|sur le cote) gauche$", {"action": "snap_left"}),
            (r"^(?:mets|met|place|deplace|colle) " + _WIN + r" (?:a|sur la|sur le cote) droite$", {"action": "snap_right"}),
            (r"^(?:montre|affiche) (?:toutes )?(?:les|mes) fenetres$|^vue des taches$", {"action": "task_view"}),
        ],
        parameters={"action": {"type": "string", "enum": ACTIONS}},
        required=["action"],
        priority=76,
    ),
]
