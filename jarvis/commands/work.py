"""Work helpers: send messages (WhatsApp, email), ask Claude/ChatGPT/Perplexity, and work on the
selected text of any application (summarize, translate, fix, rewrite, explain, read aloud).

Sending a message always asks for a spoken "oui" first and repeats the recipient and the text.
Known contacts (phone numbers, email addresses) go in config.json, section "contacts":
    "contacts": {"paul": {"whatsapp": "+33612345678", "email": "paul@example.com"}}
"""
from __future__ import annotations

import os
import re
import time
from urllib.parse import quote

from jarvis import pcctl
from jarvis.commands import Command, CommandContext
from jarvis.logger import get_logger
from jarvis.textnorm import simple

log = get_logger(__name__)


# ---------------------------------------------------------------------------------------
# Contacts and messages
# ---------------------------------------------------------------------------------------
def _contact(ctx: CommandContext, name: str) -> dict:
    book = {simple(k): v for k, v in (ctx.cfg.get("contacts") or {}).items() if isinstance(v, dict)}
    key = simple(name or "")
    if key in book:
        return book[key]
    for k, v in book.items():  # "Paul" matches "paul martin"
        if key and (key in k.split() or k in key.split()):
            return v
    return {}


def _email_address(ctx: CommandContext, contact: str) -> str:
    if "@" in (contact or ""):
        return contact.strip()
    return _contact(ctx, contact).get("email", "")


def _confirm_message(args: dict) -> str | None:
    app = (args.get("app") or "whatsapp").lower()
    text, contact = (args.get("text") or "").strip(), (args.get("contact") or "").strip()
    if app == "email":
        return f"J'envoie un mail à {contact} : « {text} ». D'accord ? Réponds oui ou non."
    return f"J'envoie à {contact} sur WhatsApp : « {text} ». Je l'envoie ? Réponds oui ou non."


def send_message(ctx: CommandContext, args: dict) -> str:
    app = (args.get("app") or "whatsapp").lower()
    contact, text = (args.get("contact") or "").strip(), (args.get("text") or "").strip()
    if not contact or not text:
        return "À qui, et quel message ?"
    if app == "email":
        return _send_email(ctx, contact, text, (args.get("subject") or "").strip())
    return _send_whatsapp(ctx, contact, text)


def _send_whatsapp(ctx: CommandContext, contact: str, text: str) -> str:
    phone = re.sub(r"[^\d+]", "", str(_contact(ctx, contact).get("whatsapp") or _contact(ctx, contact).get("phone") or ""))
    pcctl.mark_app_opened()
    try:
        if phone:  # direct link: opens the right chat with the message ready
            os.startfile(f"whatsapp://send?phone={phone.lstrip('+')}&text={quote(text)}")  # noqa: S606
        else:
            os.startfile("whatsapp:")  # noqa: S606
    except OSError:
        return "WhatsApp n'est pas installé sur ce PC."
    hwnd = pcctl.wait_for_target(9.0)
    if not hwnd or "whatsapp" not in pcctl.window_info(hwnd)[1].lower():
        return "WhatsApp ne s'est pas ouvert au premier plan, je n'envoie rien."
    if phone:
        time.sleep(1.5)            # the chat loads with the text already typed
    else:
        pcctl.send_combo("ctrl+f")  # search the chat by name, open the first result
        time.sleep(0.5)
        pcctl.paste_text(contact)
        time.sleep(1.6)
        pcctl.send_combo("enter")
        time.sleep(1.2)
        pcctl.paste_text(text)
        time.sleep(0.4)
    pcctl.send_combo("enter")
    log.info("WhatsApp message sent to %r", contact)
    return f"Message envoyé à {contact}."


def _send_email(ctx: CommandContext, contact: str, text: str, subject: str) -> str:
    address = _email_address(ctx, contact)
    url = f"mailto:{quote(address)}?subject={quote(subject)}&body={quote(text)}"
    pcctl.mark_app_opened()
    try:
        os.startfile(url)  # noqa: S606 - opens the default mail app with a draft
    except OSError:
        return "Aucune application de mail n'est configurée sur ce PC."
    if not address:
        return f"Le brouillon est prêt. Je n'ai pas l'adresse de {contact} : ajoute-la, puis envoie."
    hwnd = pcctl.wait_for_target(9.0)
    if not hwnd:
        return "Le brouillon est ouvert, mais je n'ai pas pu l'envoyer : vérifie-le et envoie-le."
    time.sleep(1.0)
    pcctl.send_combo("ctrl+enter")  # "send" in Outlook, Mail and Gmail
    return f"Mail envoyé à {contact}. Vérifie qu'il est bien parti."


# ---------------------------------------------------------------------------------------
# Claude / ChatGPT / Perplexity in the browser
# ---------------------------------------------------------------------------------------
WEB_AI = {
    "claude": ("https://claude.ai/new?q={}", "Claude"),
    "chatgpt": ("https://chatgpt.com/?q={}", "ChatGPT"),
    "perplexity": ("https://www.perplexity.ai/search?q={}", "Perplexity"),
}


def ask_web_ai(ctx: CommandContext, args: dict) -> str:
    service = simple(args.get("service") or "claude").replace(" ", "")
    service = "chatgpt" if service.startswith(("chat", "gpt", "tchat")) else service
    url, label = WEB_AI.get(service, WEB_AI["claude"])
    prompt = (args.get("prompt") or "").strip()
    pcctl.mark_app_opened()
    os.startfile(url.format(quote(prompt)))  # noqa: S606 - fixed sites, the prompt is URL-encoded
    return f"Je pose la question à {label}."


# ---------------------------------------------------------------------------------------
# Selected text: summarize, translate, fix, rewrite, explain, read
# ---------------------------------------------------------------------------------------
TASKS = {
    "summarize": ("Résume ce texte en deux ou trois phrases orales.", "speak"),
    "explain": ("Explique simplement ce texte (ou ce code) en deux ou trois phrases orales.", "speak"),
    "fix": ("Corrige l'orthographe, la grammaire et la ponctuation. Garde le sens, la langue et la mise en forme.", "replace"),
    "rewrite": ("Reformule ce texte de façon plus claire et professionnelle, dans la même langue.", "replace"),
    "read": ("", "speak"),
}


def _copy_selection() -> str:
    previous = pcctl.get_clipboard()
    pcctl.set_clipboard("")
    pcctl.send_combo("ctrl+c")
    time.sleep(0.35)
    text = (pcctl.get_clipboard() or "").strip()
    if previous is not None:
        pcctl.set_clipboard(previous)
    return text


def selection(ctx: CommandContext, args: dict) -> str | None:
    task = args.get("task") or "summarize"
    lang = (args.get("language") or "").strip()
    hwnd = pcctl.wait_for_target(1.0)
    if not hwnd:
        return "Je ne trouve pas de fenêtre active."
    text = _copy_selection()
    if not text:
        return "Sélectionne d'abord le texte, puis redemande-moi."
    if task == "read":
        return text[:1500]
    if task == "translate":
        instruction, output = (f"Traduis ce texte en {lang or 'anglais'}. Garde la mise en forme.", "replace")
    elif task == "custom":
        instruction, output = (args.get("instruction") or "Améliore ce texte."), args.get("output") or "replace"
    else:
        instruction, output = TASKS.get(task, TASKS["summarize"])
    if ctx.brain is None:
        return "Je n'ai pas accès à l'IA pour ça."
    if output == "replace":
        if pcctl.is_shell(hwnd):
            return "Par sécurité, je ne modifie pas un terminal."
        system = ("Tu transformes le texte de l'utilisateur selon la consigne. Réponds UNIQUEMENT avec le texte final, "
                  "sans commentaire, sans guillemets, sans Markdown ajouté.")
    else:
        system = ctx.cfg["ai"]["system_prompt"] + " Réponds en une à trois phrases."
    result = ctx.brain.complete(system, f"Consigne : {instruction}\n\nTexte :\n{text[:6000]}")
    if not result:
        return "Je n'ai pas réussi, réessaie."
    if output == "replace":
        pcctl.focus(hwnd)
        pcctl.paste_text(result)  # the selection is still active: pasting replaces it
        return "C'est fait."
    return result


_SEL = r"(?:\s+(?:ce texte|ce paragraphe|ce mail|cet email|ce code|ca|cela|la selection|le texte selectionne|this|that|the text|the selection|this text))?"
COMMANDS = [
    Command(
        name="send_message",
        description="Send a message for the user: app 'whatsapp' (default) or 'email'. Write the final message text "
                    "(in the user's words, polished if asked). The user is always asked to confirm before sending.",
        run=send_message,
        confirm=_confirm_message,
        parameters={
            "app": {"type": "string", "enum": ["whatsapp", "email"]},
            "contact": {"type": "string", "description": "Contact name (or email address)"},
            "text": {"type": "string", "description": "The exact message to send"},
            "subject": {"type": "string", "description": "Email subject (email only)"},
        },
        required=["contact", "text"],
        priority=60,
    ),
    Command(
        name="ask_web_ai",
        description="Ask a question to Claude, ChatGPT or Perplexity in the browser (opens the site with the question).",
        run=ask_web_ai,
        patterns=[
            r"^(?:demande|demander|pose la question) a (?P<service>claude|chat ?gpt|chat j ?pt|perplexity)(?:,| de| si| :)?\s+(?P<prompt>.+)$",
            r"^ask (?P<service>claude|chat ?gpt|perplexity)(?: to| if| :|,)?\s+(?P<prompt>.+)$",
        ],
        parameters={"service": {"type": "string", "enum": ["claude", "chatgpt", "perplexity"]},
                    "prompt": {"type": "string", "description": "The question, as the user wants it asked"}},
        required=["service", "prompt"],
        priority=78,
    ),
    Command(
        name="selected_text",
        description="Work on the text the user has selected in any application: summarize, explain, read (aloud), fix "
                    "(spelling), rewrite, translate (with language), or custom (with instruction and output 'replace' or "
                    "'speak'). 'fix', 'rewrite', 'translate' replace the selection.",
        run=selection,
        patterns=[
            (r"^(?:resume|resumer|resumes|summarize|summarise)" + _SEL + r"$", {"task": "summarize"}),
            (r"^(?:explique|expliquer|explain)(?:-moi| moi)?" + _SEL + r"$", {"task": "explain"}),
            (r"^(?:lis|lit|lire|read)(?: moi|-moi)?" + _SEL + r"(?: a voix haute| aloud)?$", {"task": "read"}),
            (r"^(?:corrige|corriger|fix)" + _SEL + r"(?: les fautes| l'orthographe| the spelling)?$", {"task": "fix"}),
            (r"^corrige les fautes(?: de ce texte)?$|^corrige l'orthographe$", {"task": "fix"}),
            (r"^(?:reformule|reformuler|ameliore|rewrite|improve)" + _SEL + r"$", {"task": "rewrite"}),
            (r"^(?:traduis|traduire|translate)" + _SEL + r" (?:en|in|into|to) (?P<language>\w+)$", {"task": "translate"}),
        ],
        parameters={
            "task": {"type": "string", "enum": ["summarize", "explain", "read", "fix", "rewrite", "translate", "custom"]},
            "language": {"type": "string", "description": "Target language for translate"},
            "instruction": {"type": "string", "description": "What to do, for custom"},
            "output": {"type": "string", "enum": ["replace", "speak"]},
        },
        required=["task"],
        priority=77,
    ),
]
