"""Music: play local music or search YouTube/Spotify, and media keys (pause, next, previous)."""
from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path
from urllib.parse import quote, quote_plus

from jarvis.commands import Command, CommandContext
from jarvis.commands._words import PLAY, PUT
from jarvis.textnorm import simple
from jarvis.winctl import known_folder, open_target, press_key

AUDIO_EXT = {".mp3", ".m4a", ".flac", ".wav", ".ogg", ".wma", ".aac", ".opus"}


def _music_folder(ctx: CommandContext) -> Path:
    custom = ctx.cfg.get("commands", {}).get("music_folder")
    return Path(custom) if custom else known_folder("music")


def play_music(ctx: CommandContext, args: dict) -> str:
    query = (args.get("query") or "").strip()
    service = simple(args.get("service") or "")
    if not query:
        folder = _music_folder(ctx)
        files = [p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT] if folder.exists() else []
        if files:
            random.shuffle(files)
            playlist = Path(tempfile.gettempdir()) / "jarvis_playlist.m3u"
            playlist.write_text("\n".join(str(p) for p in files[:300]), encoding="utf-8")
            open_target(str(playlist))
            return f"Je lance votre musique, {len(files)} morceaux en lecture aléatoire."
        open_target("https://music.youtube.com")
        return "Je n'ai pas trouvé de musique sur l'ordinateur, j'ouvre YouTube Music."
    if service == "spotify":
        open_target(f"spotify:search:{quote(query)}")
        return f"Je cherche {query} sur Spotify."
    open_target("https://www.youtube.com/results?search_query=" + quote_plus(query))
    return f"Je cherche {query} sur YouTube."


def media(ctx: CommandContext, args: dict) -> str | None:
    action = args["action"]
    key = {"pause": "play_pause", "play": "play_pause", "next": "next", "previous": "previous", "stop": "stop"}[action]
    press_key(key)
    return {"pause": "Pause.", "play": "Lecture.", "next": "Morceau suivant.", "previous": "Morceau précédent.",
            "stop": "J'arrête la lecture."}[action]


_MUSIC = r"(?:de la |la |ma |une |des |de |du )?(?:musique|zik|chanson|playlist|son)s?"

COMMANDS = [
    Command(
        name="media_control",
        description="Control the music/video currently playing: pause, play (resume), next, previous, stop.",
        run=media,
        patterns=[
            (r"^(?:pause|" + PUT + r" (?:la musique |la video |la lecture |le son )?en pause|arrete la musique|stoppe la musique|coupe la musique|stop la musique)$", {"action": "pause"}),
            (r"^(?:reprends?|reprenez|relance la musique|continue la musique|lecture|play|remets la musique|remet la musique)$", {"action": "play"}),
            (r"^(?:suivant|suivante|(?:chanson|morceau|piste|musique|titre) suivante?|passe a la suivante|next|passe la chanson|change de chanson|zappe)$", {"action": "next"}),
            (r"^(?:precedent|precedente|(?:chanson|morceau|piste|musique|titre) precedente?|reviens en arriere|la precedente)$", {"action": "previous"}),
        ],
        parameters={"action": {"type": "string", "enum": ["pause", "play", "next", "previous", "stop"]}},
        required=["action"],
        priority=40,
    ),
    Command(
        name="play_music",
        description="Play music: without a query, the user's local music; with a query (artist, song, genre), "
                    "search it on YouTube (or Spotify if asked).",
        run=play_music,
        patterns=[
            # "mets de la musique", "lance ma playlist"
            r"^(?:" + PLAY + r"|lance|lancez)\s+(?:moi\s+)?" + _MUSIC + r"$",
            # "joue du Daft Punk", "écoute la chanson X"  (only unambiguous verbs here)
            r"^(?:joue|jouez|jouer|ecoute|ecouter|passe[ -]moi)\s+(?:moi\s+)?(?:la chanson\s+|le titre\s+|l'album\s+|la musique de\s+|du\s+|de la\s+|des\s+|de\s+)?(?P<query>.+?)(?:\s+sur\s+(?P<service>youtube|spotify|youtube music))?$",
            # "mets la chanson X", "lance l'album X"
            r"^(?:" + PUT + r"|lance|lancez)\s+(?:moi\s+)?(?:la chanson|le titre|l'album|la musique de|un morceau de|une chanson de)\s+(?P<query>.+?)(?:\s+sur\s+(?P<service>youtube|spotify|youtube music))?$",
            # "mets X sur YouTube"
            r"^(?:" + PUT + r"|lance|lancez)\s+(?:moi\s+)?(?P<query>.+?)\s+sur\s+(?P<service>youtube|spotify|youtube music)$",
        ],
        parameters={"query": {"type": "string", "description": "Artist, song or genre; empty for local music"},
                    "service": {"type": "string", "enum": ["youtube", "spotify"]}},
        priority=15,
    ),
]
