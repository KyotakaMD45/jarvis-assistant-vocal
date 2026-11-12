"""Switch the AI brain by voice: Claude, Groq, Gemini or OpenAI."""
from __future__ import annotations

from jarvis.commands import Command, CommandContext
from jarvis.textnorm import simple

# What the offline speech model really hears for each name (tested), plus common forms.
ALIASES = {
    "claude": ["claude", "cloud", "clode", "clod", "anthropic", "claude ai"],
    "groq": ["groq", "grok", "grop", "grob", "grock", "groc k", "groc", "grog", "grotte", "gros", "greco", "brock", "croc", "grosse", "grok ai"],
    "gemini": ["gemini", "jemini", "gemmini", "gemini ai", "google gemini"],
    "openai": ["openai", "open ai", "open hay", "open a i", "open eye", "hop anais", "gpt", "chatgpt",
               "chat gpt", "open ia", "open i a"],
}


def provider_from_text(text: str) -> str | None:
    key = simple(text)
    for prefix in ("le modele ", "l'ia ", "l ia ", "l'intelligence artificielle ", "le cerveau ", "le ", "la ", "l "):
        if key.startswith(prefix):
            key = key[len(prefix):]
    for name, words in ALIASES.items():
        if key in words or any(key.startswith(w + " ") for w in words):
            return name
    return None


def switch_ai(ctx: CommandContext, args: dict) -> str:
    name = args.get("provider")
    name = name if name in ALIASES else provider_from_text(name or "")
    if not name:
        return "Je connais Claude, Groq, Gemini et OpenAI. Lequel voulez-vous ?"
    return ctx.brain.switch(name)


def which_ai(ctx: CommandContext, args: dict) -> str:
    return ctx.brain.describe()


COMMANDS = [
    Command(
        name="switch_ai",
        ai_tool=False,
        description="Switch the assistant's AI provider to claude, groq, gemini or openai.",
        run=switch_ai,
        patterns=[r"^(?:passe|pas|passez|bascule|basculez|basculer|change|changez|utilise|utilisez|prends|active|mets|mais)"
                  r"\s+(?:sur|a|en|vers|pour|avec)?\s*(?:le modele\s+|l'ia\s+|l ia\s+|ton cerveau\s+(?:sur\s+)?)?(?P<provider>.+)$"],
        accept=lambda args: provider_from_text(args.get("provider", "")) is not None,
        parameters={"provider": {"type": "string", "enum": ["claude", "groq", "gemini", "openai"]}},
        required=["provider"],
        priority=80,
    ),
    Command(
        name="which_ai",
        description="Say which AI provider and model are in use.",
        run=which_ai,
        patterns=[r"^(?:quel(?:le)?|tu utilises quel(?:le)?|c'est quel(?:le)?)\s+(?:ia|modele|intelligence artificielle|cerveau|moteur)",
                  r"^(?:tu es quel(?:le)? ia|qui es tu)$"],
        ai_tool=False,
        priority=80,
    ),
]
