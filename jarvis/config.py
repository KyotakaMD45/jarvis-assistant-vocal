"""Load config.json, merged over safe defaults. A broken file never crashes Jarvis."""
from __future__ import annotations

import copy
import json
import re
from typing import Any

from jarvis.paths import CONFIG_PATH


DEFAULTS: dict[str, Any] = {
    "assistant_name": "Jarvis",
    "language": "fr-FR",
    "log_level": "INFO",
    "ai": {
        "provider": "claude",
        "max_tokens": 2048,
        "timeout_seconds": 10,
        "max_retries": 1,
        "history_turns": 6,
        "use_tools": True,
        "system_prompt": (
            "Tu es Jarvis, un assistant vocal calme, précis et efficace. "
            "Réponds toujours en français, en une à trois phrases courtes, "
            "sans listes ni mise en forme Markdown, car ta réponse sera lue à voix haute. "
            "Ne donne plus de détails que si l'utilisateur le demande."
        ),
        "claude": {"model": "claude-opus-5-5", "effort": "low", "refusal_fallback": True},
        "groq": {"model": "openai/gpt-oss-120b", "base_url": "https://api.groq.com/openai/v1"},
        "gemini": {"model": "gemini-2.5-flash", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
        "openai": {"model": "gpt-4.1-mini", "base_url": "https://api.openai.com/v1"},
    },
    "commands": {
        "music_folder": "",
    },
    "voice": {
        "voice": "fr-FR-HenriNeural",
        "pitch": "-25Hz",
        "rate": "-5%",
        "volume": "+0%",
        "offline_rate": 165,
        "offline_language": "fr",
        "test_sentence": "Bonjour monsieur. Tous les systèmes sont opérationnels. Je suis prêt.",
    },
    "listening": {
        "wake_words": ["jarvis"],
        "wake_alternatives": [],
        "model_path": "models/vosk-model-small-fr-0.22",
        "input_device": None,
        "command_timeout_seconds": 7,
        "follow_up_seconds": 8,
        "wake_sound": True,
        "cloud_transcription": "groq",
        "barge_in": True,
        "wake_nbest": 10,
        "wake_grammar": True,
        "cloud_model": "whisper-large-v3-turbo",
    },
    "hud": {
        "enabled": True,
        "low_power": False,
        "fps": 30,
        "fullscreen": False,
        "maximized": True,
        "width": 1280,
        "height": 760,
        "sounds": True,
    },
}

VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
_RATE = re.compile(r"^[+-]\d{1,3}%$")
_PITCH = re.compile(r"^[+-]\d{1,3}Hz$")
_VOICE = re.compile(r"^[a-z]{2,3}-[A-Z]{2}-[A-Za-z]+Neural$")


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _sanitize_voice(cfg: dict) -> list[str]:
    warnings: list[str] = []
    voice, vdef = cfg["voice"], DEFAULTS["voice"]
    for key, pattern, example in (
        ("voice", _VOICE, "fr-FR-HenriNeural"),
        ("pitch", _PITCH, "-25Hz"),
        ("rate", _RATE, "-5%"),
        ("volume", _RATE, "+0%"),
    ):
        value = voice.get(key)
        if not isinstance(value, str) or not pattern.match(value):
            warnings.append(f"voice.{key} '{value}' is invalid (example: '{example}'), using '{vdef[key]}'")
            voice[key] = vdef[key]
    rate = voice.get("offline_rate")
    if not isinstance(rate, int) or isinstance(rate, bool) or not 80 <= rate <= 300:
        warnings.append(f"voice.offline_rate '{rate}' is invalid (expected 80-300), using {vdef['offline_rate']}")
        voice["offline_rate"] = vdef["offline_rate"]
    for key in ("offline_language", "test_sentence"):
        if not isinstance(voice.get(key), str) or not voice[key].strip():
            voice[key] = vdef[key]

    listening, ldef = cfg["listening"], DEFAULTS["listening"]
    words = listening.get("wake_words")
    if isinstance(words, str):
        words = [words]
    if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words) or not words:
        warnings.append("listening.wake_words is invalid, using [\"jarvis\"]")
        words = ldef["wake_words"]
    listening["wake_words"] = [w.strip().lower() for w in words]
    alternatives = listening.get("wake_alternatives")
    if not isinstance(alternatives, list) or not all(isinstance(w, str) for w in alternatives):
        if alternatives is not None:
            warnings.append("listening.wake_alternatives must be a list of words, ignoring it")
        alternatives = []
    listening["wake_alternatives"] = [w.strip().lower() for w in alternatives if w.strip()]
    for key, low, high in (("command_timeout_seconds", 2, 30), ("follow_up_seconds", 0, 30)):
        value = listening.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
            warnings.append(f"listening.{key} '{value}' is invalid (expected {low}-{high}), using {ldef[key]}")
            listening[key] = ldef[key]
    if not isinstance(listening.get("model_path"), str):
        listening["model_path"] = ldef["model_path"]
    if listening.get("input_device") is not None and not isinstance(listening["input_device"], (int, str)):
        warnings.append("listening.input_device must be null, a device number or a name; using the default microphone")
        listening["input_device"] = None
    listening["wake_sound"] = bool(listening.get("wake_sound"))
    listening["barge_in"] = bool(listening.get("barge_in", True))
    nbest = listening.get("wake_nbest", 10)
    listening["wake_nbest"] = nbest if isinstance(nbest, int) and 0 <= nbest <= 30 else 10
    listening["wake_grammar"] = bool(listening.get("wake_grammar", True))
    if listening.get("cloud_transcription") not in ("groq", "off"):
        warnings.append("listening.cloud_transcription must be \"groq\" or \"off\", using \"groq\"")
        listening["cloud_transcription"] = "groq"
    if not isinstance(listening.get("cloud_model"), str) or not listening["cloud_model"].strip():
        listening["cloud_model"] = ldef["cloud_model"]

    hud, hdef = cfg["hud"], DEFAULTS["hud"]
    for key, low, high in (("fps", 10, 60), ("width", 640, 7680), ("height", 480, 4320)):
        value = hud.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            warnings.append(f"hud.{key} '{value}' is invalid (expected {low}-{high}), using {hdef[key]}")
            hud[key] = hdef[key]
    for key in ("enabled", "low_power", "fullscreen", "maximized", "sounds"):
        hud[key] = bool(hud.get(key, hdef[key]))
    if hud["low_power"]:
        hud["fps"] = min(hud["fps"], 20)
    return warnings


def _sanitize(cfg: dict) -> list[str]:
    """Fix invalid values in place and return a list of warnings."""
    warnings: list[str] = []
    for section in ("ai", "voice", "listening", "hud", "commands"):
        if not isinstance(cfg.get(section), dict):
            warnings.append(f"'{section}' section is invalid, using defaults")
            cfg[section] = copy.deepcopy(DEFAULTS[section])
    warnings.extend(_sanitize_voice(cfg))
    ai, defaults = cfg["ai"], DEFAULTS["ai"]

    for key, low, high in (
        ("max_tokens", 256, 64000),
        ("timeout_seconds", 3, 600),
        ("max_retries", 0, 5),
        ("history_turns", 0, 50),
    ):
        value = ai.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not low <= value <= high:
            warnings.append(f"ai.{key} '{value}' is invalid (expected {low}-{high}), using {defaults[key]}")
            ai[key] = defaults[key]
    if ai.get("provider") not in ("claude", "groq", "gemini", "openai"):
        warnings.append(f"ai.provider '{ai.get('provider')}' is invalid (claude, groq, gemini, openai), using claude")
        ai["provider"] = "claude"
    if not isinstance(ai.get("system_prompt"), str) or not ai["system_prompt"].strip():
        ai["system_prompt"] = defaults["system_prompt"]
    ai["use_tools"] = bool(ai.get("use_tools", True))
    for name in ("claude", "groq", "gemini", "openai"):
        section = ai.get(name)
        if not isinstance(section, dict):
            warnings.append(f"ai.{name} section is invalid, using defaults")
            ai[name] = section = copy.deepcopy(defaults[name])
        if not isinstance(section.get("model"), str) or not section["model"].strip():
            warnings.append(f"ai.{name}.model is empty, using the default model")
            section["model"] = defaults[name]["model"]
        if name != "claude" and (not isinstance(section.get("base_url"), str) or not section["base_url"].startswith("https://")):
            section["base_url"] = defaults[name]["base_url"]
    claude = ai["claude"]
    if claude.get("effort") not in VALID_EFFORTS:
        warnings.append(f"ai.claude.effort '{claude.get('effort')}' is invalid, using 'low'")
        claude["effort"] = "low"
    claude["refusal_fallback"] = bool(claude.get("refusal_fallback"))
    if not isinstance(cfg["commands"].get("music_folder"), str):
        cfg["commands"]["music_folder"] = ""
    return warnings


def _migrate(user_cfg: dict) -> dict:
    """Config files from step 1-3 had a top-level "claude" section: move it into "ai"."""
    old = user_cfg.pop("claude", None)
    if isinstance(old, dict):
        ai = user_cfg.setdefault("ai", {})
        claude = ai.setdefault("claude", {})
        for key in ("model", "effort", "refusal_fallback"):
            if key in old:
                claude.setdefault(key, old[key])
        for key in ("max_tokens", "timeout_seconds", "max_retries", "history_turns", "system_prompt"):
            if key in old:
                ai.setdefault(key, old[key])
    return user_cfg


def load_config() -> tuple[dict, list[str]]:
    """Return (config, warnings). Falls back to defaults on any problem."""
    warnings: list[str] = []
    user_cfg: dict = {}
    if CONFIG_PATH.exists():
        try:
            user_cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            if not isinstance(user_cfg, dict):
                raise ValueError("top level must be a JSON object")
        except (OSError, ValueError) as exc:
            warnings.append(f"config.json could not be read ({exc}); using default settings")
            user_cfg = {}
    else:
        warnings.append("config.json not found; using default settings")

    cfg = _deep_merge(DEFAULTS, _migrate(user_cfg))
    warnings.extend(_sanitize(cfg))
    return cfg, warnings
