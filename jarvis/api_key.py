"""Read and write the AI API keys stored in .env (never hardcoded)."""
from __future__ import annotations

import os

from jarvis.paths import ENV_PATH
from jarvis.providers import PROVIDERS

KEY_NAME = PROVIDERS["claude"].env_key  # kept for older imports
KEY_PREFIX = PROVIDERS["claude"].key_prefix


def clean_key(raw: str) -> str:
    """Remove whitespace, quotes and invisible characters that sneak in when pasting a key."""
    return raw.replace("﻿", "").strip().strip('"').strip("'").strip()


def looks_like_key(key: str, provider: str = "claude") -> bool:
    prefix = PROVIDERS[provider].key_prefix
    return key.startswith(prefix) and len(key) > 20 and " " not in key


def _read_env_file() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = clean_key(value)
    return values


def get_api_key(provider: str = "claude") -> tuple[str, str]:
    """Return (key, source). The .env file wins over a system environment variable,
    so an old key left in Windows settings can never shadow the new one."""
    env_name = PROVIDERS[provider].env_key
    key = _read_env_file().get(env_name, "")
    if key:
        return key, ".env"
    key = clean_key(os.environ.get(env_name, ""))
    if key:
        return key, "environment variable"
    return "", "none"


def save_api_key(key: str, provider: str = "claude") -> None:
    """Write the key to .env, keeping any other lines already there."""
    env_name = PROVIDERS[provider].env_key
    lines: list[str] = []
    try:
        lines = ENV_PATH.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        pass
    lines = [line for line in lines if not line.strip().startswith(f"{env_name}=")]
    lines.append(f"{env_name}={key}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mask(key: str) -> str:
    if len(key) < 16:
        return "***"
    return f"{key[:8]}...{key[-4:]}"
