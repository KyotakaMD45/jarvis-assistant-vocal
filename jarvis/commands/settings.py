"""Windows settings: open a settings page, dark/light mode."""
from __future__ import annotations

import os
import winreg

from jarvis.commands import Command, CommandContext

PAGES = {
    "wifi": ("ms-settings:network-wifi", "le Wi-Fi"),
    "bluetooth": ("ms-settings:bluetooth", "le Bluetooth"),
    "network": ("ms-settings:network-status", "le réseau"),
    "display": ("ms-settings:display", "l'affichage"),
    "sound": ("ms-settings:sound", "le son"),
    "battery": ("ms-settings:batterysaver", "la batterie"),
    "power": ("ms-settings:powersleep", "l'alimentation"),
    "update": ("ms-settings:windowsupdate", "Windows Update"),
    "apps": ("ms-settings:appsfeatures", "les applications"),
    "notifications": ("ms-settings:notifications", "les notifications"),
    "background": ("ms-settings:personalization-background", "le fond d'écran"),
    "personalization": ("ms-settings:personalization", "la personnalisation"),
    "storage": ("ms-settings:storagesense", "le stockage"),
    "mouse": ("ms-settings:mousetouchpad", "la souris"),
    "keyboard": ("ms-settings:typing", "le clavier"),
    "date": ("ms-settings:dateandtime", "la date et l'heure"),
    "language": ("ms-settings:regionlanguage", "la langue"),
    "privacy": ("ms-settings:privacy", "la confidentialité"),
    "accounts": ("ms-settings:yourinfo", "le compte"),
    "home": ("ms-settings:", "les paramètres"),
}
_THEME_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"


def _set_theme(dark: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _THEME_KEY, 0, winreg.KEY_SET_VALUE) as key:
        for name in ("AppsUseLightTheme", "SystemUsesLightTheme"):
            winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, 0 if dark else 1)


def settings(ctx: CommandContext, args: dict) -> str:
    page = args.get("page", "home")
    if page in ("dark_mode", "light_mode"):
        _set_theme(page == "dark_mode")
        return "Mode sombre activé." if page == "dark_mode" else "Mode clair activé."
    uri, label = PAGES.get(page, PAGES["home"])
    os.startfile(uri)  # noqa: S606 - fixed ms-settings URIs
    return f"J'ouvre les paramètres pour {label}." if page != "home" else "J'ouvre les paramètres."


_W = {
    "wifi": r"(?:du |le )?wi[ -]?fi|wifi", "bluetooth": r"(?:du |le )?bluetooth", "network": r"(?:du |le )?reseau|(?:d')?internet",
    "display": r"(?:de l')?(?:affichage|ecran)", "sound": r"(?:du |le )?son|(?:de l')?audio", "battery": r"(?:de la )?batterie",
    "power": r"(?:de l')?alimentation|(?:de la )?mise en veille", "update": r"(?:des )?mises? a jour|windows update",
    "apps": r"(?:des )?applications", "notifications": r"(?:des )?notifications", "background": r"(?:du )?fond d'ecran",
    "storage": r"(?:du )?stockage", "mouse": r"(?:de la )?souris|(?:du )?pave tactile", "keyboard": r"(?:du )?clavier",
    "date": r"(?:de la )?date|(?:de l')?heure", "language": r"(?:de la )?langue", "privacy": r"(?:de la )?confidentialite",
}
_OPEN = r"(?:ouvre|ouvrez|affiche|montre|va dans|va sur)"
COMMANDS = [
    Command(
        name="windows_settings",
        description="Open a Windows settings page (wifi, bluetooth, network, display, sound, battery, power, update, "
                    "apps, notifications, background, personalization, storage, mouse, keyboard, date, language, privacy, "
                    "accounts, home) or switch Windows to dark_mode / light_mode.",
        run=settings,
        patterns=[
            *[(r"^" + _OPEN + r" (?:les )?(?:parametres|reglages) (?:" + rx + r")$", {"page": key}) for key, rx in _W.items()],
            *[(r"^(?:" + _OPEN + r" )?(?:les )?(?:parametres|reglages) (?:" + rx + r")$", {"page": key}) for key, rx in _W.items()],
            (r"^(?:" + _OPEN + r" )?(?:les )?(?:parametres|reglages)(?: windows| de windows)?$", {"page": "home"}),
            (r"^(?:mets|met|passe|active)(?: windows| l'ordinateur| le pc)? (?:en |le )?(?:mode sombre|theme sombre|dark mode)$", {"page": "dark_mode"}),
            (r"^(?:mets|met|passe|active)(?: windows| l'ordinateur| le pc)? (?:en |le )?(?:mode clair|theme clair|light mode)$", {"page": "light_mode"}),
        ],
        parameters={"page": {"type": "string", "enum": sorted(PAGES) + ["dark_mode", "light_mode"]}},
        required=["page"],
        priority=72,
    ),
]
