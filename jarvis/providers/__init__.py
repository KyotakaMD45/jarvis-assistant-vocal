"""AI providers Jarvis can use, and how to reach them."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    label: str          # spoken / displayed name
    env_key: str        # variable name in .env
    key_prefix: str     # quick format check
    keys_url: str       # where to create a key


PROVIDERS: dict[str, ProviderInfo] = {
    "claude": ProviderInfo("claude", "Claude", "ANTHROPIC_API_KEY", "sk-ant-", "https://console.anthropic.com/settings/keys"),
    "groq": ProviderInfo("groq", "Groq", "GROQ_API_KEY", "gsk_", "https://console.groq.com/keys"),
    "gemini": ProviderInfo("gemini", "Gemini", "GEMINI_API_KEY", "AIza", "https://aistudio.google.com/apikey"),
    "openai": ProviderInfo("openai", "OpenAI", "OPENAI_API_KEY", "sk-", "https://platform.openai.com/api-keys"),
}


def create(name: str, ai_cfg: dict, api_key: str):
    """Build the client object for a provider (SDKs are imported lazily)."""
    from jarvis.jiter_fallback import ensure_jiter

    ensure_jiter()  # before the SDK import: Windows may block jiter's DLL
    if name == "claude":
        from jarvis.providers.claude import ClaudeProvider

        return ClaudeProvider(ai_cfg, api_key)
    from jarvis.providers.openai_compat import OpenAICompatProvider

    return OpenAICompatProvider(name, ai_cfg, api_key)
