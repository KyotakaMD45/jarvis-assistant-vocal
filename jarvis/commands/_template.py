"""TEMPLATE - copy this file to add a command (files starting with "_" are ignored).

1. Copy it to e.g. jarvis/commands/weather_alert.py (any name without a leading "_").
2. Write a `run` function: it receives the context and the arguments, and returns the
   French sentence Jarvis will say (or None to stay silent).
3. Describe when it triggers:
   - `patterns`: regexes tested on the sentence in lowercase WITHOUT accents
     ("ouvre le bloc-notes" -> "ouvre le bloc-notes", "Arrête" -> "arrete").
     Named groups (?P<name>...) become arguments, with the original accents kept.
   - `description` + `parameters`: used by the AI to call the command when the user
     phrases it differently. Set ai_tool=False to disable that.
4. Restart Jarvis (tray icon > Restart, or say "redémarre-toi"). That's all.
"""
from jarvis.commands import Command, CommandContext


def say_hello(ctx: CommandContext, args: dict) -> str:
    name = args.get("name") or "monsieur"
    return f"Bonjour {name} !"


COMMANDS = [
    Command(
        name="say_hello",                                    # unique name (also the AI tool name)
        description="Greet someone by name.",                # English, for the AI
        run=say_hello,
        patterns=[r"^(?:dis|dit) bonjour a (?P<name>.+)$"],  # "dis bonjour à Marie"
        parameters={"name": {"type": "string", "description": "Who to greet"}},
        required=["name"],
        # confirm="Êtes-vous sûr ?",  # uncomment to ask for a spoken "oui" first
        priority=0,                    # higher priorities are tried first
    ),
]
