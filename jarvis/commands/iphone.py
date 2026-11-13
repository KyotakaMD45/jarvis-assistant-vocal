"""Pair an iPhone (or any phone) on the same Wi-Fi: "connecte mon iPhone" / "déconnecte mon iPhone"."""
from __future__ import annotations

import os

from jarvis.commands import Command, CommandContext


def connect_phone(ctx: CommandContext, args: dict) -> str:
    assistant = ctx.assistant
    if assistant is None or getattr(assistant, "on_remote_pair", None) is None:
        return "La connexion du téléphone n'est disponible qu'avec l'interface."
    try:
        url = assistant.on_remote_pair()
    except OSError as exc:
        return f"Je n'arrive pas à ouvrir la connexion pour le téléphone : {exc}."
    if not url:
        return "La connexion du téléphone n'est disponible qu'avec l'interface."
    from jarvis.paths import ROOT
    from jarvis.remote import make_qr

    path = make_qr(url, ROOT / "iphone_qr.png")
    os.startfile(path)  # noqa: S606 - our own QR image
    if assistant.ui is not None:
        assistant.ui.log("system", f"iPhone : scannez le code QR, ou ouvrez {url}")
    return ("Scannez le code QR affiché avec l'appareil photo de votre iPhone, monsieur. Le téléphone doit être "
            "sur le même Wi-Fi. Si Windows demande l'accès au réseau, autorisez les réseaux privés.")


def disconnect_phone(ctx: CommandContext, args: dict) -> str:
    assistant = ctx.assistant
    if assistant is None or getattr(assistant, "on_remote_unpair", None) is None:
        return "Aucun téléphone n'est connecté."
    assistant.on_remote_unpair()
    return "Téléphone déconnecté. L'ancien code ne fonctionne plus."


COMMANDS = [
    Command(name="connect_phone", description="Pair the user's iPhone / phone with Apex (shows a QR code).",
            run=connect_phone, ai_tool=False, priority=90,
            patterns=[r"^(?:connecte|associe|relie|appaire|jumelle|ajoute) (?:mon|un|le) (?:iphone|telephone|portable|phone)$",
                      r"^(?:connect|pair) my (?:iphone|phone)$"]),
    Command(name="disconnect_phone", description="Unpair the phone (the old QR code stops working).",
            run=disconnect_phone, ai_tool=False, priority=90,
            patterns=[r"^(?:deconnecte|dissocie|oublie|retire) (?:mon|le) (?:iphone|telephone|portable|phone)$",
                      r"^(?:disconnect|unpair) my (?:iphone|phone)$"]),
]
