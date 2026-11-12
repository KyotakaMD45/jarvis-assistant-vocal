"""Keyboard control of the active window: shortcuts, typing/dictation, scrolling, clipboard."""
from __future__ import annotations

import time

from jarvis import pcctl
from jarvis.commands import Command, CommandContext, Unsure

# Fixed list of shortcuts (never an arbitrary key sequence).
SHORTCUTS = {
    "copy": ("ctrl+c", "Copié."), "paste": ("ctrl+v", "Collé."), "cut": ("ctrl+x", "Coupé."),
    "undo": ("ctrl+z", "Annulé."), "redo": ("ctrl+y", "Rétabli."), "select_all": ("ctrl+a", "Tout est sélectionné."),
    "save": ("ctrl+s", "Enregistré."), "new": ("ctrl+n", "Nouveau document."), "find": ("ctrl+f", None),
    "print": ("ctrl+p", None), "new_tab": ("ctrl+t", None), "close_tab": ("ctrl+w", None),
    "reopen_tab": ("ctrl+shift+t", None), "next_tab": ("ctrl+tab", None), "previous_tab": ("ctrl+shift+tab", None),
    "refresh": ("f5", None), "back": ("alt+left", None), "forward": ("alt+right", None),
    "zoom_in": ("ctrl+plus", None), "zoom_out": ("ctrl+minus", None), "zoom_reset": ("ctrl+0", None),
    "fullscreen": ("f11", None), "enter": ("enter", None), "escape": ("esc", None), "tab": ("tab", None),
    "backspace": ("backspace", None), "delete": ("delete", None), "page_up": ("pageup", None),
    "page_down": ("pagedown", None), "top": ("ctrl+home", None), "bottom": ("ctrl+end", None),
    "scroll_up": (None, None), "scroll_down": (None, None),
    "click": (None, None), "double_click": (None, None), "right_click": (None, None),
}
NEEDS_SAFE_TARGET = {"enter", "paste"}  # could run a command in a terminal


def _target(ctx: CommandContext):
    hwnd = pcctl.wait_for_target(6.0 if ctx.from_ai else 1.0)
    if not hwnd:
        raise RuntimeError("no target")
    return hwnd


def shortcut(ctx: CommandContext, args: dict) -> str | None:
    action = args.get("action", "")
    if action not in SHORTCUTS:
        return "Je ne connais pas ce raccourci."
    combo, spoken = SHORTCUTS[action]
    try:
        hwnd = _target(ctx)
    except RuntimeError:
        return "Je ne trouve pas de fenêtre active."
    if action in NEEDS_SAFE_TARGET and pcctl.is_shell(hwnd):
        return "Par sécurité, je n'agis pas dans un terminal."
    times = max(1, min(20, int(args.get("times") or 1)))
    for _ in range(times):
        if action in ("click", "double_click", "right_click"):
            pcctl.click("right" if action == "right_click" else "left", double=action == "double_click")
        elif action == "scroll_up":
            pcctl.scroll(5)
        elif action == "scroll_down":
            pcctl.scroll(-5)
        else:
            pcctl.send_combo(combo)
        time.sleep(0.05)
    return spoken if spoken else ""


GENERATIVE = ("un ", "une ", "du ", "des ", "moi ", "m'", "nous ", "quelque", "le code", "la fonction", "le programme")


def type_text(ctx: CommandContext, args: dict) -> str | None:
    text = (args.get("text") or "").strip()
    if not text:
        return "Que dois-je écrire ?"
    if not ctx.from_ai and text.lower().startswith(GENERATIVE):
        raise Unsure  # "écris un code qui..." -> the AI writes it, then calls this tool
    try:
        hwnd = _target(ctx)
    except RuntimeError:
        return "Ouvrez d'abord la fenêtre où je dois écrire."
    if pcctl.is_shell(hwnd):
        return "Par sécurité, je n'écris pas dans un terminal."
    if pcctl.last_target_fresh and ctx.from_ai:
        # App opened for this request (VS Code, Word...): write in a new document, not on its start page.
        pcctl.send_combo("ctrl+n")
        time.sleep(0.9)
    previous = pcctl.get_clipboard()
    if not pcctl.set_clipboard(text):
        return "Le presse-papier est occupé, réessayez."
    pcctl.send_combo("ctrl+v")
    time.sleep(0.6)
    if previous is not None:
        pcctl.set_clipboard(previous)  # give the user their clipboard back
    lines = text.count("\n") + 1
    return "C'est écrit." if lines == 1 else f"C'est écrit, {lines} lignes."


def read_clipboard(ctx: CommandContext, args: dict) -> str:
    text = (pcctl.get_clipboard() or "").strip()
    if not text:
        return "Le presse-papier est vide."
    return text if len(text) <= 400 else text[:400] + "… et la suite."


_KEY = r"(?:appuie|appuyez|tape|presse|fais|fait)\s+(?:sur\s+)?(?:la touche\s+)?"
COMMANDS = [
    Command(
        name="keyboard_shortcut",
        description="Press a keyboard shortcut or key in the active window (new = new document/file).",
        run=shortcut,
        patterns=[
            (r"^(?:copie|copier|copiez)(?: ca| sa| le texte| la selection| tout)?$", {"action": "copy"}),
            (r"^(?:colle|coller|collez)(?: ca| sa| le texte| ici)?$", {"action": "paste"}),
            (r"^(?:coupe|couper|coupez) (?:ca|le texte|la selection)$", {"action": "cut"}),
            (r"^(?:annule la derniere action|annule ce que j'ai fait|ctrl z|controle z)$", {"action": "undo"}),
            (r"^(?:retablis|retablir|refais|ctrl y|controle y)$", {"action": "redo"}),
            (r"^(?:selectionne|selectionner|selectionnez) tout$|^tout selectionner$", {"action": "select_all"}),
            (r"^(?:enregistre|enregistrer|enregistrez|sauvegarde|sauvegarder|sauvegardez)(?: le fichier| le document| ca| tout)?$", {"action": "save"}),
            (r"^(?:cree|creer|ouvre) un nouveau (?:fichier|document)$|^nouveau (?:fichier|document)$", {"action": "new"}),
            (r"^(?:ouvre |ouvrir )?(?:un )?nouvel onglet$", {"action": "new_tab"}),
            (r"^(?:ferme|fermer|fermez) (?:l'onglet|cet onglet|l onglet|l'anglais|l anglais|l'onglais|longlet)$", {"action": "close_tab"}),
            (r"^(?:rouvre|rouvrir|reouvre) (?:l'onglet|l'anglais|le dernier onglet)$", {"action": "reopen_tab"}),
            (r"^onglet suivant$", {"action": "next_tab"}),
            (r"^onglet precedent$", {"action": "previous_tab"}),
            (r"^(?:actualise|actualiser|rafraichis|rafraichir|recharge|recharger)(?: la page)?$", {"action": "refresh"}),
            (r"^(?:page precedente|reviens en arriere|retour en arriere)$", {"action": "back"}),
            (r"^page suivante$", {"action": "forward"}),
            (r"^(?:zoome|zoomer|zoom avant|agrandis le texte)$", {"action": "zoom_in"}),
            (r"^(?:dezoome|dezoomer|zoom arriere|reduis le texte)$", {"action": "zoom_out"}),
            (r"^(?:mets |passe )?(?:en )?plein ecran$", {"action": "fullscreen"}),
            (r"^(?:" + _KEY + r")?(?:entree|entrer)$|^valide$|^valider$", {"action": "enter"}),
            (r"^(?:" + _KEY + r")?(?:echap|echappe|escape)$", {"action": "escape"}),
            (r"^(?:descends|defile|fais defiler|scrolle|scroll)(?: vers le bas| en bas| la page)?$", {"action": "scroll_down"}),
            (r"^(?:remonte|defile vers le haut|fais defiler vers le haut|scrolle vers le haut|monte la page)$", {"action": "scroll_up"}),
            (r"^(?:clique|clic|click|cliquer)(?: ici| la| dessus)?$", {"action": "click"}),
            (r"^(?:double[ -]?clique|double[ -]?clic|double[ -]?click)(?: ici| la| dessus)?$", {"action": "double_click"}),
            (r"^(?:clic droit|clique droit|clique avec le bouton droit|right[ -]click)$", {"action": "right_click"}),
            (r"^(?:va |vas |aller )?tout en haut(?: de la page)?$", {"action": "top"}),
            (r"^(?:va |vas |aller )?tout en bas(?: de la page)?$", {"action": "bottom"}),
        ],
        parameters={
            "action": {"type": "string", "enum": sorted(SHORTCUTS)},
            "times": {"type": "integer", "description": "How many times (default 1)"},
        },
        required=["action"],
        priority=75,
    ),
    Command(
        name="type_text",
        description="Type text or code into the application that has the keyboard focus (editor, document, browser "
                    "field, chat). Pass the exact final text; for code pass only the complete code, without explanation. "
                    "To write in an application that is not open yet, call open_app first.",
        run=type_text,
        patterns=[r"^(?:ecris|ecrit|ecrivez|ecrire|tape|tapez|taper|dicte|saisis)\s+(?P<text>.+)$"],
        # "écris un poème / un code qui..." is a request for the AI (which then calls this tool).
        accept=lambda args: not (args.get("text") or "").lower().startswith(GENERATIVE),
        parameters={"text": {"type": "string", "description": "The exact text or code to type"}},
        required=["text"],
        priority=74,
    ),
    Command(
        name="read_clipboard",
        description="Read aloud the text currently in the clipboard.",
        run=read_clipboard,
        patterns=[r"^(?:lis|lit|lire|dis moi|qu'est-ce qu'il y a dans|que contient) (?:le )?presse[ -]papiers?$"],
        priority=74,
    ),
]
