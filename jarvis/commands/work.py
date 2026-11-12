"""Work helpers: send messages (WhatsApp, email), ask Claude/ChatGPT/Perplexity, and work on the
selected text of any application (summarize, translate, fix, rewrite, explain, read aloud).

A message is typed in the app first, sent only after a spoken "oui", and the sending is checked.
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


def known_contacts() -> list[str]:
    from jarvis.state import load_state

    return [c for c in load_state().get("known_contacts", []) if isinstance(c, str)]


def _remember_contact(name: str) -> None:
    """Contacts reached once are given to the AI, which then fixes misheard names ("Benny Mahou")."""
    from jarvis.state import save_state

    name = name.strip()
    if not name:
        return
    names = [n for n in known_contacts() if n.lower() != name.lower()]
    save_state(known_contacts=([name] + names)[:40])


def _email_address(ctx: CommandContext, contact: str) -> str:
    if "@" in (contact or ""):
        return contact.strip()
    return _contact(ctx, contact).get("email", "")


def send_message(ctx: CommandContext, args: dict) -> str:
    app = (args.get("app") or "whatsapp").lower()
    contact, text = (args.get("contact") or "").strip(), (args.get("text") or "").strip()
    if not contact or not text:
        return "À qui, et quel message ?"
    if app == "email":
        return _send_email(ctx, contact, text, (args.get("subject") or "").strip())
    from jarvis import uictl

    return uictl.run(_send_whatsapp, ctx, contact, text)


_SEARCH = re.compile(r"recherch|search", re.IGNORECASE)
_COMPOSER_PREFIX = re.compile(r"^\s*(?:[ée]crivez|entrez|tapez|saisissez|type)\s+(?:un |a )?message\s*(?:[àa]|to)?\s*", re.IGNORECASE)


def _search_box(items):
    return next(((c, ct, n) for c, ct, n in items if ct == "EditControl" and _SEARCH.search(n)), None)


def _composer(items):
    return next(((c, ct, n) for c, ct, n in items if ct == "EditControl" and not _SEARCH.search(n)), None)


def _chat_name(composer) -> str:
    """'Écrivez un message à Benimaru💁❤️' -> 'Benimaru' (the open conversation)."""
    from jarvis.uictl import fold

    name = _COMPOSER_PREFIX.sub("", composer[2] if composer else "")
    clean = re.sub(r"[^\w\s'’.-]", "", name, flags=re.UNICODE).strip()
    return clean or fold(name)


def _whatsapp_window(timeout: float = 12.0):
    from jarvis import uictl

    hwnd = uictl.find_window(process="WhatsApp.Root.exe") or uictl.find_window(process="WhatsApp.exe")
    if hwnd:
        return hwnd
    try:
        os.startfile("whatsapp:")  # noqa: S606
    except OSError:
        return None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.4)
        hwnd = uictl.find_window(process="WhatsApp.Root.exe") or uictl.find_window(process="WhatsApp.exe")
        if hwnd:
            return hwnd
    return None


def _send_whatsapp(ctx: CommandContext, contact: str, text: str) -> str:
    """Open the right chat (fuzzy name match on screen), type the message, confirm, send, verify."""
    from jarvis import uictl

    book = _contact(ctx, contact)
    wanted = book.get("name") or contact
    hwnd = _whatsapp_window()
    if not hwnd:
        return "WhatsApp n'est pas installé ou ne s'ouvre pas."
    pcctl.user32.ShowWindow(hwnd, pcctl.SW_RESTORE) if pcctl.user32.IsIconic(hwnd) else None
    uictl.bring_front(hwnd)
    items = uictl.wait_for(hwnd, lambda it: it if _search_box(it) else None, timeout=8.0)
    if not items:
        return "Je n'arrive pas à lire WhatsApp. Il est peut-être en train de se connecter."
    composer = _composer(items)
    if not (composer and uictl.name_score(wanted, _chat_name(composer)) >= 0.75):
        # 1) the chats already on screen; 2) WhatsApp search with the first letters only (its search
        # wants exact text, and the spoken name is often misspelled: "Benny Mahou" for "Benimaru");
        # 3) the full name. Each time, the closest name on screen wins.
        def chat_rows():
            return [(c, ct, n) for c, ct, n in uictl.elements(hwnd) if ct in ("DataItemControl", "ListItemControl") and n]

        rows = chat_rows()
        hit = uictl.best_match(rows, wanted, minimum=0.6)
        letters = uictl.fold(wanted).replace(" ", "")[:3]
        for query in ([letters] if len(letters) >= 2 else []) + [wanted]:
            if hit:
                break
            uictl.type_into(_search_box(uictl.elements(hwnd, kinds={"EditControl"}))[0], query)
            time.sleep(1.2)
            rows = chat_rows()
            hit = uictl.best_match(rows, wanted, minimum=0.6)
        if not hit:
            others = []
            for _c, _ct, n in rows[:6]:
                first = " ".join(re.sub(r"[^\w\s'’-]", " ", n).split()[:2])
                if first and first not in others:
                    others.append(first)
            pcctl.send_combo("esc")
            return f"Je ne trouve pas {contact} dans WhatsApp." + (f" Les plus proches : {', '.join(others[:3])}." if others else "")
        uictl.click(hit[0])
        items = uictl.wait_for(hwnd, lambda it: it if _composer(it) else None, timeout=5.0) or []
        composer = _composer(items)
        if not composer or uictl.name_score(wanted, _chat_name(composer)) < 0.6:
            return f"Je n'ai pas réussi à ouvrir la discussion avec {contact}, je n'envoie rien."
    shown = _chat_name(composer) or contact
    if not uictl.type_into(composer[0], text):
        return "Je n'arrive pas à écrire dans WhatsApp."
    if not ctx.ask_yes_no(f"J'envoie à {shown} : « {text} » ?"):
        uictl.bring_front(hwnd)
        uictl.type_into(composer[0], " ")
        pcctl.send_combo("backspace")
        return "D'accord, je n'envoie pas. Le message est effacé."
    uictl.bring_front(hwnd)
    try:
        composer[0].SetFocus()
    except Exception:  # noqa: BLE001
        pass
    pcctl.send_combo("enter")
    # Check: the field empties once the message is sent.
    for _ in range(8):
        time.sleep(0.35)
        now = _composer(uictl.elements(hwnd, kinds={"EditControl"}))
        if now and not uictl.value_of(now[0]).strip():
            log.info("WhatsApp message sent and verified (%s)", shown)
            _remember_contact(shown)
            return f"Message envoyé à {shown}, monsieur."
    log.warning("WhatsApp send could not be verified (%s)", shown)
    return f"J'ai appuyé sur envoyer, mais je n'arrive pas à le vérifier. Vérifiez WhatsApp, s'il vous plaît."


def _send_email(ctx: CommandContext, contact: str, text: str, subject: str) -> str:
    address = _email_address(ctx, contact)
    url = f"mailto:{quote(address)}?subject={quote(subject)}&body={quote(text)}"
    pcctl.mark_app_opened()
    try:
        os.startfile(url)  # noqa: S606 - opens the default mail app with a draft
    except OSError:
        return "Aucune application de mail n'est configurée sur ce PC."
    if not address:
        return f"Le brouillon est prêt. Je n'ai pas l'adresse de {contact} : ajoutez-la, puis envoyez."
    hwnd = pcctl.wait_for_target(9.0)
    if not hwnd:
        return "Le brouillon est ouvert, mais je n'ai pas pu l'envoyer : vérifie-le et envoie-le."
    if not ctx.ask_yes_no(f"Le mail pour {address} est prêt. Je l'envoie ?"):
        return "D'accord, le brouillon reste ouvert."
    pcctl.focus(hwnd)
    time.sleep(0.3)
    pcctl.send_combo("ctrl+enter")  # "send" in Outlook, Mail and Gmail
    return f"Mail envoyé à {contact}. Vérifiez qu'il est bien parti."


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
        return "Sélectionnez d'abord le texte, puis redemandez-moi."
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
        description="Send a WhatsApp message (default) or an email for the user. The user confirms before sending.",
        run=send_message,
        parameters={
            "app": {"type": "string", "enum": ["whatsapp", "email"]},
            "contact": {"type": "string"},
            "text": {"type": "string"},
            "subject": {"type": "string"},
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
        description="Work on the text selected in any app (fix/rewrite/translate replace it; custom = instruction).",
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
            "language": {"type": "string"},
            "instruction": {"type": "string"},
            "output": {"type": "string", "enum": ["replace", "speak"]},
        },
        required=["task"],
        priority=77,
    ),
]
