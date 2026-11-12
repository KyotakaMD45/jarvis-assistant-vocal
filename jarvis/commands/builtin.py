"""Commands that control Jarvis itself (quit, restart, voice test, help...)."""
from __future__ import annotations

from jarvis.commands import Command, CommandContext


def _assistant(ctx: CommandContext):
    return ctx.assistant


def quit_jarvis(ctx: CommandContext, args: dict) -> str:
    if ctx.assistant is not None:
        ctx.assistant.request_quit()
    return "Au revoir, monsieur."


def goodbye(ctx: CommandContext, args: dict) -> str:
    """"Au revoir" / "bye" end the conversation; Knull keeps running in the background."""
    return "À votre service, monsieur."


def learn_voice(ctx: CommandContext, args: dict) -> str:
    if ctx.assistant is None:
        return "Disponible seulement en mode vocal."
    return ctx.assistant.enroll_voice()


def forget_voice(ctx: CommandContext, args: dict) -> str:
    if ctx.assistant is None:
        return "Disponible seulement en mode vocal."
    return ctx.assistant.forget_voice()


def restart_jarvis(ctx: CommandContext, args: dict) -> str:
    if ctx.assistant is not None:
        ctx.assistant.request_restart()
    return "Je redémarre."


def cancel(ctx: CommandContext, args: dict) -> None:
    return None


def reset(ctx: CommandContext, args: dict) -> str:
    if ctx.brain is not None:
        ctx.brain.reset()
    return "C'est noté, je repars de zéro."


def voice_test(ctx: CommandContext, args: dict) -> str | None:
    if ctx.assistant is not None:
        ctx.assistant.voice_test()
        return None
    return ctx.cfg["voice"]["test_sentence"]


def diagnostic(ctx: CommandContext, args: dict) -> str:
    from jarvis.diagnostics import run_diagnostics

    failures = run_diagnostics(ctx.cfg, [], voice=False)
    if failures == 0:
        return "Diagnostic terminé. Tous les systèmes fonctionnent."
    return "Diagnostic terminé. J'ai trouvé des problèmes, les détails sont à l'écran et dans le journal."


def show_hud(ctx: CommandContext, args: dict) -> str:
    if ctx.assistant is not None:
        ctx.assistant.show_hud()
    return "Voici l'interface."


def hide_hud(ctx: CommandContext, args: dict) -> str:
    if ctx.assistant is not None:
        ctx.assistant.hide_hud()
    return "Je cache l'interface. Je reste à l'écoute."


def help_text(ctx: CommandContext, args: dict) -> str:
    return ("Je peux ouvrir ou fermer des applications, des dossiers et des sites, chercher sur internet, "
            "donner l'heure et la date, créer des rappels et des minuteurs, lancer de la musique, "
            "régler le volume et la luminosité, faire une capture d'écran, verrouiller ou éteindre l'ordinateur, "
            "et changer d'intelligence artificielle : Claude, Groq, Gemini ou OpenAI. Pour le reste, posez-moi simplement votre question.")


COMMANDS = [
    # Quitting the program needs an explicit order AND a spoken "oui" (speech recognition sometimes
    # invents "au revoir" on short noises, which used to switch Knull off).
    Command(name="quit_jarvis", description="Quit Knull completely.", run=quit_jarvis, ai_tool=False, priority=100,
            confirm="Voulez-vous vraiment que je m'éteigne complètement ? Répondez oui ou non.",
            patterns=[r"^(?:arrete[ -]toi|eteins[ -]toi|eteint[ -]toi|quitte|quitte[ -]toi|quit|exit|desactive[ -]toi|shut down|switch off)(?: completement| jarvis| apex| knull| null| nul)?$"]),
    Command(name="goodbye", description="End the conversation (Knull keeps running).", run=goodbye, ai_tool=False, priority=100,
            patterns=[r"^(?:(?:ok |bon |merci |je (?:te )?dis )*au revoir|bonne nuit|bye(?: bye)?|a plus tard|a plus|a la prochaine|goodbye|good night|see you)(?: jarvis| apex| knull| null| nul)?$"]),
    Command(name="restart_jarvis", description="Restart Jarvis.", run=restart_jarvis, ai_tool=False, priority=100,
            patterns=[r"^(?:redemarre[ -]toi|redemarrez[ -]vous|relance[ -]toi|redemarre jarvis|relance jarvis|redemarre apex|relance apex|redemarre knull|relance knull|reboot|restart)$"]),
    Command(name="learn_voice", description="Learn the owner's voice.", run=learn_voice, ai_tool=False, priority=100,
            patterns=[r"^(?:apprends|apprend|enregistre|memorise|reconnais) ma voix$|^learn my voice$"]),
    Command(name="forget_voice", description="Forget the owner's voice print.", run=forget_voice, ai_tool=False,
            priority=100, patterns=[r"^(?:oublie|efface|supprime) ma voix$|^forget my voice$"]),
    Command(name="cancel", description="Cancel / never mind.", run=cancel, ai_tool=False, priority=100,
            patterns=[r"^(?:stop|annule|annuler|laisse tomber|rien|tais[ -]toi|non merci|c'est bon|oublie)$"]),
    Command(name="reset_conversation", description="Forget the conversation.", run=reset, ai_tool=False, priority=100,
            patterns=[r"^(?:nouvelle conversation|oublie tout|reinitialise|reset|on recommence)$"]),
    Command(name="voice_test", description="Play the voice test sentence.", run=voice_test, ai_tool=False, priority=100,
            patterns=[r"^(?:voice test|test vocal|test vocale|test de la voix|teste ta voix|test voix|test de voix)$"]),
    Command(name="diagnostic", description="Run the self-test.", run=diagnostic, ai_tool=False, priority=100,
            patterns=[r"^(?:diagnostic|lance le diagnostic|test systeme|lance le test|verifie les systemes|fais un diagnostic)$"]),
    Command(name="show_hud", description="Show the Jarvis interface window.", run=show_hud, ai_tool=False, priority=100,
            patterns=[r"^(?:affiche|montre|ouvre|ouvrez)[ -](?:toi|l'interface|l interface|le hud|ton interface)$"]),
    Command(name="hide_hud", description="Hide the Jarvis interface window.", run=hide_hud, ai_tool=False, priority=100,
            patterns=[r"^(?:cache|masque|reduis|ferme)[ -](?:toi|l'interface|l interface|le hud|ton interface)$"]),
    Command(name="help", description="List what Jarvis can do.", run=help_text, ai_tool=False, priority=100,
            patterns=[r"^(?:aide|help|que sais[ -]tu faire|qu'est ce que tu sais faire|qu'est[ -]ce que tu peux faire|tu sais faire quoi|que peux[ -]tu faire)$"]),
]
