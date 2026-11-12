"""Find installed applications by (spoken) name.

Sources, in order: a table of common French names -> Windows commands, the Start menu
shortcuts, and the Store apps (Get-StartApps, loaded in the background at startup).
"""
from __future__ import annotations

import difflib
import json
import os
import subprocess
import threading
from pathlib import Path

from jarvis.logger import get_logger
from jarvis.textnorm import simple
from jarvis.winctl import CREATE_NO_WINDOW

log = get_logger(__name__)

# Spoken name (folded) -> (display name, target). "@name" targets are looked up in the index.
ALIASES: dict[str, tuple[str, str]] = {}
for names, display, target in [
    (["bloc notes", "bloc note", "notepad", "bloc notes windows"], "le Bloc-notes", "notepad.exe"),
    (["calculatrice", "calculette", "calculator", "calcul"], "la calculatrice", "calc.exe"),
    (["explorateur", "explorateur de fichiers", "explorateur windows", "fichiers", "mes fichiers"], "l'explorateur", "explorer.exe"),
    (["parametres", "reglages", "parametre", "parametres windows", "configuration"], "les paramètres", "ms-settings:"),
    (["gestionnaire des taches", "gestionnaire de taches", "gestionnaire de tache"], "le gestionnaire des tâches", "taskmgr.exe"),
    (["invite de commande", "invite de commandes", "cmd", "terminal", "console"], "le terminal", "wt.exe|cmd.exe"),
    (["powershell"], "PowerShell", "powershell.exe"),
    (["panneau de configuration"], "le panneau de configuration", "control.exe"),
    (["paint"], "Paint", "mspaint.exe"),
    (["word", "microsoft word"], "Word", "winword.exe"),
    (["excel", "microsoft excel"], "Excel", "excel.exe"),
    (["powerpoint", "power point"], "PowerPoint", "powerpnt.exe"),
    (["outlook"], "Outlook", "outlook.exe"),
    (["edge", "microsoft edge", "navigateur", "le navigateur", "internet"], "le navigateur", "msedge.exe"),
    (["chrome", "google chrome"], "Chrome", "chrome.exe|@google chrome"),
    (["firefox", "mozilla firefox"], "Firefox", "firefox.exe|@firefox"),
    (["store", "microsoft store", "boutique"], "le Microsoft Store", "ms-windows-store:"),
    (["appareil photo", "camera", "webcam"], "l'appareil photo", "microsoft.windows.camera:"),
    (["horloge", "alarme", "alarmes", "reveil"], "l'horloge", "ms-clock:"),
    (["photos", "galerie"], "Photos", "ms-photos:"),
    (["calendrier", "agenda"], "le calendrier", "outlookcal:"),
    (["vs code", "visual studio code", "vscode"], "Visual Studio Code", "@visual studio code"),
    (["spotify"], "Spotify", "@spotify|spotify:"),
    (["whatsapp", "whats app", "watsapp", "wattsapp", "what s app"], "WhatsApp", "@whatsapp|whatsapp:"),
    (["discord"], "Discord", "@discord"),
    (["steam"], "Steam", "@steam|steam:"),
    (["vlc"], "VLC", "@vlc media player|vlc.exe"),
    (["teams", "microsoft teams"], "Teams", "@microsoft teams|@teams|msteams:"),
    (["capture", "outil capture", "outil de capture"], "l'outil Capture", "ms-screenclip:"),
]:
    for name in names:
        ALIASES[name] = (display, target)

_SKIP = ("uninstall", "desinstall", "readme", "documentation", "help", "aide", "release notes", "website", "site web")


class AppIndex:
    def __init__(self):
        self._apps: dict[str, tuple[str, str]] = {}   # folded name -> (display, target)
        self._lock = threading.Lock()
        self._ready = threading.Event()

    def load_async(self) -> None:
        threading.Thread(target=self._load, name="app-index", daemon=True).start()

    def wait(self, timeout: float = 6.0) -> None:
        if not self._ready.is_set() and not any(t.name == "app-index" for t in threading.enumerate()):
            self._load()
        self._ready.wait(timeout)

    def _load(self) -> None:
        apps: dict[str, tuple[str, str]] = {}
        roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
                 Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs"]
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if path.suffix.lower() in (".lnk", ".url", ".appref-ms"):
                    key = simple(path.stem)
                    if key and not any(s in key for s in _SKIP):
                        apps.setdefault(key, (path.stem, str(path)))
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                capture_output=True, timeout=20, creationflags=CREATE_NO_WINDOW,
            ).stdout.decode("utf-8", "replace")
            for item in json.loads(out or "[]"):
                key = simple(item.get("Name", ""))
                if key and not any(s in key for s in _SKIP):
                    apps.setdefault(key, (item["Name"], f"shell:AppsFolder\\{item['AppID']}"))
        except Exception as exc:  # noqa: BLE001
            log.warning("Store apps not indexed: %r", exc)
        with self._lock:
            self._apps = apps
        self._ready.set()
        log.info("Indexed %d applications", len(apps))

    def _lookup_index(self, key: str) -> tuple[str, str] | None:
        with self._lock:
            apps = dict(self._apps)
        if key in apps:
            return apps[key]
        starts = [k for k in apps if k.startswith(key + " ") or k.startswith(key)]
        if starts:
            return apps[min(starts, key=len)]
        contains = [k for k in apps if f" {key}" in f" {k}"]
        if contains:
            return apps[min(contains, key=len)]
        close = difflib.get_close_matches(key, list(apps), n=1, cutoff=0.8)
        return apps[close[0]] if close else None

    def find(self, spoken: str) -> tuple[str, str] | None:
        """Return (display name, target to open) or None."""
        key = simple(spoken)
        if not key:
            return None
        if key in ALIASES:
            display, targets = ALIASES[key]
            for target in targets.split("|"):
                if target.startswith("@"):
                    self.wait()
                    found = self._lookup_index(target[1:])
                    if found:
                        return display, found[1]
                elif target.endswith(".exe") and not _exe_available(target):
                    continue
                else:
                    return display, target
            return None
        self.wait()
        return self._lookup_index(key)


def _exe_available(exe: str) -> bool:
    """True if Windows can start this exe by name (PATH or App Paths registry)."""
    import shutil
    import winreg

    if shutil.which(exe):
        return True
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            winreg.CloseKey(winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{exe}"))
            return True
        except OSError:
            continue
    return False


INDEX = AppIndex()
