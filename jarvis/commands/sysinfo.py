"""Computer information: processor, memory, disk space, IP address, uptime."""
from __future__ import annotations

import ctypes
import shutil
import socket
import time

from jarvis.commands import Command, CommandContext
from jarvis.system_stats import SystemStats


def _local_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # UDP "connect" sends nothing; it only picks the interface
            return s.getsockname()[0]
    except OSError:
        return None


def info(ctx: CommandContext, args: dict) -> str:
    what = args.get("what", "all")
    parts = []
    if what in ("cpu", "ram", "all"):
        reader = SystemStats()
        reader.read()        # the CPU load is measured between two readings
        time.sleep(0.5)
        stats = reader.read()
        if what in ("cpu", "all") and stats.get("cpu") is not None:
            parts.append(f"le processeur est à {round(stats['cpu'])} pour cent")
        if what in ("ram", "all") and stats.get("ram") is not None:
            parts.append(f"la mémoire est utilisée à {round(stats['ram'])} pour cent")
    if what in ("disk", "all"):
        usage = shutil.disk_usage("C:\\")
        parts.append(f"il reste {usage.free / 1e9:.0f} gigaoctets libres sur le disque C, sur {usage.total / 1e9:.0f}")
    if what == "ip":
        ip = _local_ip()
        return f"Votre adresse IP locale est {ip}." if ip else "Vous ne semblez pas connecté à un réseau."
    if what == "uptime":
        ms = ctypes.windll.kernel32.GetTickCount64()
        hours, minutes = int(ms // 3_600_000), int(ms // 60_000 % 60)
        return f"L'ordinateur est allumé depuis {hours} heures et {minutes} minutes." if hours else \
            f"L'ordinateur est allumé depuis {minutes} minutes."
    if not parts:
        return "Je n'arrive pas à lire cette information."
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + "."


COMMANDS = [
    Command(
        name="system_info",
        description="Tell computer information (cpu, ram, disk space, local ip, uptime, all).",
        run=info,
        patterns=[
            (r"(?:utilisation|charge|etat) (?:du )?(?:processeur|cpu)|combien (?:utilise|consomme) le processeur", {"what": "cpu"}),
            (r"(?:utilisation|etat) (?:de la )?(?:memoire|ram)|combien de (?:memoire|ram)", {"what": "ram"}),
            (r"(?:espace|place) (?:libre |disque |restant )*(?:sur le |du |de mon )?(?:disque|pc|ordinateur)?|combien (?:de place|d'espace)", {"what": "disk"}),
            (r"(?:mon |mon adresse |l'adresse |quelle est mon adresse )ip\b|adresse ip\b", {"what": "ip"}),
            (r"(?:depuis combien de temps|depuis quand) (?:l'ordinateur|le pc|l'ordi) est allume", {"what": "uptime"}),
            (r"^(?:etat|etat du systeme|etat de l'ordinateur|comment va (?:le pc|l'ordinateur|mon pc)|diagnostic systeme)$", {"what": "all"}),
        ],
        parameters={"what": {"type": "string", "enum": ["cpu", "ram", "disk", "ip", "uptime", "all"]}},
        required=["what"],
        priority=65,
    ),
]
