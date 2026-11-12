"""Files: search the PC (Explorer search), empty the recycle bin."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
from urllib.parse import quote

from jarvis.commands import Command, CommandContext


def search(ctx: CommandContext, args: dict) -> str:
    query = (args.get("query") or "").strip(" .?!")
    if not query:
        return "Quel fichier dois-je chercher ?"
    os.startfile(f"search-ms:query={quote(query)}&crumb=location:{quote(str(Path.home()))}")  # noqa: S606
    return f"Je cherche {query} dans vos fichiers."


def empty_bin(ctx: CommandContext, args: dict) -> str:
    # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND (Jarvis already asked for a spoken "oui").
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return "La corbeille est vidée." if result in (0, -2147418113) else "La corbeille est déjà vide."


COMMANDS = [
    Command(
        name="search_files",
        description="Search the user's files and folders by name (opens the Windows Explorer search).",
        run=search,
        patterns=[r"^(?:cherche|recherche|trouve|retrouve)(?: moi)? (?:le |les |mon |mes )?(?:fichiers?|documents?|dossiers?|photos?) (?P<query>.+)$"],
        parameters={"query": {"type": "string", "description": "Words of the file name"}},
        required=["query"],
        priority=66,
    ),
    Command(
        name="empty_recycle_bin",
        ai_tool=False,
        description="Empty the Windows recycle bin (asks for confirmation).",
        run=empty_bin,
        confirm="Voulez-vous vraiment vider la corbeille ? Les fichiers seront supprimés définitivement. Répondez oui ou non.",
        patterns=[r"^(?:vide|vider|videz|nettoie) (?:la )?corbeille$"],
        priority=66,
    ),
]
