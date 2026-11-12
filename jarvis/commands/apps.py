"""Open and close applications, folders and websites."""
from __future__ import annotations

from jarvis.app_index import INDEX
import re

from jarvis.commands import Command, CommandContext, Unsure
from jarvis.commands._words import ART, CLOSE, OPEN
from jarvis.commands.web import resolve_site
from jarvis.textnorm import simple
from jarvis.winctl import close_window, known_folder, list_windows, open_target

FOLDERS = {
    "documents": ("documents", "vos documents"), "mes documents": ("documents", "vos documents"),
    "telechargements": ("downloads", "les téléchargements"), "telechargement": ("downloads", "les téléchargements"),
    "downloads": ("downloads", "les téléchargements"),
    "images": ("pictures", "vos images"), "photos": ("pictures", "vos images"), "mes images": ("pictures", "vos images"),
    "musique": ("music", "votre musique"), "ma musique": ("music", "votre musique"),
    "videos": ("videos", "vos vidéos"), "mes videos": ("videos", "vos vidéos"),
    "bureau": ("desktop", "le bureau"),
}
_FILLER = ("application ", "appli ", "app ", "logiciel ", "programme ", "fenetre de ", "fenetre ", "fenetres ",
           "ferme ", "ouvre ", "lance ", "le ", "la ", "les ", "l ", "mon ", "ma ", "mes ", "un ", "une ", "cette ", "ce ")
# Words that end the application name: "ferme WhatsApp que tu viens d'ouvrir" -> "whatsapp".
_TAIL = re.compile(r"\s(?:que|qui|quand|parce|pour|stp|svp|merci|s il|maintenant|tout de suite|s v p|a nouveau)\b.*$")
_COMMON = {"application", "fenetre", "logiciel", "programme", "ouvre", "ferme", "lance", "moi", "avec", "dans", "pour",
           "tout", "tous", "cette", "celle", "celui", "encore", "vite", "bien", "juste", "alors", "accord", "dis", "fais"}


def _clean_name(name: str) -> str:
    key = simple(re.split(r"[.,;!?]", name, maxsplit=1)[0])
    key = _TAIL.sub("", key)
    changed = True
    while changed:
        changed = False
        for word in _FILLER:
            if key.startswith(word):
                key = key[len(word):]
                changed = True
    return key.strip()


def _find_app(key: str):
    """The whole name first, then each meaningful word ("l'appli WhatsApp de mon frère" -> WhatsApp)."""
    found = INDEX.find(key)
    if found:
        return found
    for word in key.split():
        if len(word) >= 4 and word not in _COMMON:
            found = INDEX.find(word)
            if found:
                return found
    return None


def open_app(ctx: CommandContext, args: dict) -> str:
    raw = args["app"]
    key = _clean_name(raw)
    folder_key = key.removeprefix("dossier ").removeprefix("des ").removeprefix("de ").strip()
    if key.startswith("dossier ") or folder_key in FOLDERS:
        if folder_key in FOLDERS:
            folder_id, spoken = FOLDERS[folder_key]
            open_target(str(known_folder(folder_id)))
            return f"J'ouvre {spoken}."
        return f"Je ne connais pas le dossier {raw}."
    if key.startswith("site "):
        return open_site(ctx, {"site": key[5:]})
    found = _find_app(key)
    if found:
        display, target = found
        open_target(target)
        return f"J'ouvre {display}."
    site = resolve_site(key)
    if site:
        open_target(site[1])
        return f"J'ouvre {site[0]}."
    if not ctx.from_ai:
        raise Unsure(raw)  # let the AI understand the sentence
    return f"Je n'ai pas trouvé l'application {raw}."


def open_site(ctx: CommandContext, args: dict) -> str:
    site = resolve_site(args["site"], allow_search=True)
    open_target(site[1])
    return f"J'ouvre {site[0]}."


def close_app(ctx: CommandContext, args: dict) -> str:
    raw = args["app"]
    key = _clean_name(raw)
    if not key:
        return "Quelle application dois-je fermer ?"
    if key in ("jarvis", "l'interface", "interface", "hud"):
        if ctx.assistant is not None:
            ctx.assistant.hide_hud()
        return "Je cache l'interface. Je reste à l'écoute."
    from jarvis.app_index import ALIASES

    exe = ""
    if key in ALIASES:
        exe = next((t for t in ALIASES[key][1].split("|") if t.endswith(".exe")), "")
    key = key.removeprefix("dossier ").removeprefix("des ").removeprefix("de ").strip()
    keys = [key]
    if key in FOLDERS:  # Explorer shows the localized name ("Téléchargements") or the folder name ("Downloads")
        keys.append(simple(known_folder(FOLDERS[key][0]).name))
    closed = 0
    for hwnd, title, process in list_windows():
        title_key, proc_key = simple(title), simple(process.rsplit(".", 1)[0])
        if "j a r v i s" in title_key:
            continue  # never close our own window this way
        title_hit = any(k in title_key for k in keys)
        # Process-name matches never touch the shell, Python or the UWP frame host.
        proc_hit = (key == proc_key or (exe and process.lower() == exe)) and \
            proc_key not in ("explorer", "python", "pythonw", "applicationframehost", "textinputhost")
        if title_hit or proc_hit:
            if close_window(hwnd):
                closed += 1
    if not closed:
        # Word-level fallback: "ferme la fenêtre WhatsApp que tu viens d'ouvrir" -> any window whose
        # app name is one of the words.
        words = {w for w in key.split() if len(w) >= 4 and w not in _COMMON}
        for hwnd, title, process in list_windows():
            title_key, proc_key = simple(title), simple(process.rsplit(".", 1)[0])
            if "j a r v i s" in title_key or proc_key in ("explorer", "python", "pythonw", "textinputhost"):
                continue
            if words & set(title_key.split()) or proc_key in words:
                if close_window(hwnd):
                    closed += 1
    name = key or raw
    if closed:
        return f"Je ferme {name}." if closed == 1 else f"Je ferme {closed} fenêtres {name}."
    if not ctx.from_ai:
        raise Unsure(raw)
    return f"Je ne trouve pas de fenêtre {name} ouverte."


COMMANDS = [
    Command(
        name="open_website",
        description="Open a website in the browser (e.g. youtube, gmail, a domain name).",
        run=open_site,
        patterns=[
            r"^(?:va|vas|allez|aller)\s+sur\s+(?:le site\s+(?:de\s+|d')?)?(?P<site>.+)$",
            OPEN + r"\s+le site\s+(?:de\s+|d'|web\s+)?(?P<site>.+)$",
        ],
        parameters={"site": {"type": "string", "description": "Site name or domain, e.g. 'youtube' or 'lemonde.fr'"}},
        required=["site"],
        priority=20,
    ),
    Command(
        name="open_app",
        description="Open an application installed on the computer, a personal folder "
                    "(documents, downloads, pictures, music, videos, desktop) or a well-known website.",
        run=open_app,
        patterns=[r"^" + OPEN + r"\s+" + ART + r"(?P<app>.+)$"],
        parameters={"app": {"type": "string", "description": "Application, folder or site name as the user said it"}},
        required=["app"],
        priority=10,
    ),
    Command(
        name="close_app",
        description="Close the windows of an application (politely, the app can ask to save).",
        run=close_app,
        patterns=[r"^" + CLOSE + r"\s+" + ART + r"(?P<app>.+)$"],
        parameters={"app": {"type": "string", "description": "Application name, e.g. 'chrome', 'bloc-notes'"}},
        required=["app"],
        priority=10,
    ),
]
