"""Web search (Google, YouTube, Wikipedia, Amazon...) and website resolution."""
from __future__ import annotations

import re
from urllib.parse import quote_plus

from jarvis.commands import Command, CommandContext
from jarvis.textnorm import simple
from jarvis.winctl import open_target

SITES = {
    "youtube": ("YouTube", "https://www.youtube.com"),
    "youtube music": ("YouTube Music", "https://music.youtube.com"),
    "gmail": ("Gmail", "https://mail.google.com"),
    "google": ("Google", "https://www.google.com"),
    "google maps": ("Google Maps", "https://www.google.com/maps"), "maps": ("Google Maps", "https://www.google.com/maps"),
    "facebook": ("Facebook", "https://www.facebook.com"),
    "instagram": ("Instagram", "https://www.instagram.com"),
    "twitter": ("X", "https://x.com"), "x": ("X", "https://x.com"),
    "tiktok": ("TikTok", "https://www.tiktok.com"),
    "netflix": ("Netflix", "https://www.netflix.com"),
    "amazon": ("Amazon", "https://www.amazon.fr"),
    "wikipedia": ("Wikipédia", "https://fr.wikipedia.org"), "wikipedia france": ("Wikipédia", "https://fr.wikipedia.org"),
    "linkedin": ("LinkedIn", "https://www.linkedin.com"),
    "whatsapp web": ("WhatsApp Web", "https://web.whatsapp.com"),
    "outlook web": ("Outlook", "https://outlook.live.com"), "hotmail": ("Outlook", "https://outlook.live.com"),
    "github": ("GitHub", "https://github.com"),
    "chatgpt": ("ChatGPT", "https://chatgpt.com"), "chat gpt": ("ChatGPT", "https://chatgpt.com"),
    "claude": ("Claude", "https://claude.ai"),
    "meteo": ("la météo", "https://www.google.com/search?q=m%C3%A9t%C3%A9o"),
    "actualites": ("les actualités", "https://news.google.com/?hl=fr"), "infos": ("les actualités", "https://news.google.com/?hl=fr"),
    "le bon coin": ("Leboncoin", "https://www.leboncoin.fr"), "leboncoin": ("Leboncoin", "https://www.leboncoin.fr"),
    "twitch": ("Twitch", "https://www.twitch.tv"),
    "spotify web": ("Spotify", "https://open.spotify.com"),
}

ENGINES = {
    "google": "https://www.google.com/search?q=",
    "internet": "https://www.google.com/search?q=", "le web": "https://www.google.com/search?q=",
    "le net": "https://www.google.com/search?q=",
    "youtube": "https://www.youtube.com/results?search_query=",
    "wikipedia": "https://fr.wikipedia.org/w/index.php?search=",
    "amazon": "https://www.amazon.fr/s?k=",
    "bing": "https://www.bing.com/search?q=",
}
_ENGINE_RE = "google|internet|le web|le net|youtube|wikipedia|amazon|bing"


def resolve_site(spoken: str, allow_search: bool = False) -> tuple[str, str] | None:
    """'youtube' -> ('YouTube', url); 'le monde point fr' -> ('lemonde.fr', 'https://lemonde.fr')."""
    key = simple(spoken)
    domain = re.sub(r"\s+point\s+", ".", key).replace(" ", "")  # "le monde point fr" -> lemonde.fr
    if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", domain) and not domain.startswith("site"):
        return domain, f"https://{domain}"
    for prefix in ("le site de ", "le site ", "site de ", "site ", "le ", "la ", "les ", "l "):
        if key.startswith(prefix):
            key = key[len(prefix):]
    if key in SITES:
        return SITES[key]
    domain = re.sub(r"\s+point\s+", ".", key).replace(" ", "")
    if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+(/\S*)?", domain):
        return domain, f"https://{domain}"
    if allow_search:
        return spoken, ENGINES["google"] + quote_plus(spoken)
    return None


def web_search(ctx: CommandContext, args: dict) -> str:
    query = args["query"].strip()
    engine = simple(args.get("engine") or args.get("engine2") or "google")
    base = ENGINES.get(engine, ENGINES["google"])
    open_target(base + quote_plus(query))
    where = {"youtube": " sur YouTube", "wikipedia": " sur Wikipédia", "amazon": " sur Amazon"}.get(engine, "")
    return f"Je cherche {query}{where}."


COMMANDS = [
    Command(
        name="web_search",
        description="Search the web (Google by default) or a given site (youtube, wikipedia, amazon) and open the results.",
        run=web_search,
        patterns=[
            r"^(?:cherche|cherchez|chercher|recherche|recherchez|rechercher|trouve|trouvez|google)\s+"
            r"(?:moi\s+|-moi\s+)?sur\s+(?P<engine>" + _ENGINE_RE + r")\s+(?P<query>.+)$",
            r"^(?:cherche|cherchez|chercher|recherche|recherchez|rechercher|trouve|trouvez|google)\s+"
            r"(?:moi\s+|-moi\s+)?(?:des infos sur\s+|des informations sur\s+)?(?P<query>.+?)"
            r"(?:\s+sur\s+(?P<engine2>" + _ENGINE_RE + r"))?$",
        ],
        parameters={
            "query": {"type": "string", "description": "What to search for"},
            "engine": {"type": "string", "enum": ["google", "youtube", "wikipedia", "amazon", "bing"]},
        },
        required=["query"],
        priority=15,
    ),
]
