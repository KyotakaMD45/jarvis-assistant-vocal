"""Use any application like a person: look at the window, click a button by its name, fill a field.

What Knull sees (button and field names) is passed to the AI for its next step, so it can chain
"look -> click -> type -> check" on its own.
"""
from __future__ import annotations

import time

from jarvis import pcctl
from jarvis.commands import Command, CommandContext


def _window():
    hwnd = pcctl.target_window()
    if hwnd and pcctl.foreground() != hwnd:
        pcctl.focus(hwnd)  # web apps only expose their content in the foreground
        time.sleep(0.4)
    return hwnd


def look(ctx: CommandContext, args: dict) -> str | None:
    from jarvis import uictl

    return uictl.run(_look, ctx, args)


def _look(ctx: CommandContext, args: dict) -> str | None:
    from jarvis import uictl

    hwnd = _window()
    if not hwnd:
        return "Je ne vois aucune fenêtre ouverte."
    ctx.note("Écran : " + uictl.describe(hwnd))
    return None


def click_element(ctx: CommandContext, args: dict) -> str | None:
    from jarvis import uictl

    return uictl.run(_click_element, ctx, args)


def _click_element(ctx: CommandContext, args: dict) -> str | None:
    from jarvis import uictl

    name = (args.get("name") or "").strip()
    hwnd = _window()
    if not hwnd or not name:
        return "Je ne vois pas où cliquer."
    hit = uictl.best_match(uictl.elements(hwnd), name, minimum=0.55)
    if not hit:
        ctx.note("Introuvable : " + name + ". Écran : " + uictl.describe(hwnd))
        return f"Je ne trouve pas « {name} » à l'écran."
    uictl.click(hit[0])
    ctx.note(f"Cliqué sur « {hit[2][:50]} ».")
    return None if ctx.from_ai else "C'est fait."


def fill_field(ctx: CommandContext, args: dict) -> str | None:
    from jarvis import uictl

    return uictl.run(_fill_field, ctx, args)


def _fill_field(ctx: CommandContext, args: dict) -> str | None:
    from jarvis import uictl

    field, text = (args.get("field") or "").strip(), args.get("text") or ""
    hwnd = _window()
    if not hwnd:
        return "Je ne vois aucune fenêtre ouverte."
    if pcctl.is_shell(hwnd):
        return "Par sécurité, je n'écris pas dans un terminal."
    fields = [e for e in uictl.elements(hwnd) if e[1] in ("EditControl", "ComboBoxControl", "DocumentControl")]
    hit = uictl.best_match(fields, field, minimum=0.5) if field else None
    if hit is None and fields and not field:
        hit = (fields[0][0], 1.0, fields[0][2])
    if hit is None:
        ctx.note("Champ introuvable : " + field + ". Écran : " + uictl.describe(hwnd))
        return f"Je ne trouve pas le champ « {field} »."
    uictl.type_into(hit[0], text)
    ctx.note(f"Écrit dans « {hit[2][:40]} ».")
    return None


COMMANDS = [
    Command(
        name="screen_look",
        description="Look at the window the user works in: returns its buttons, fields, rows and links (names), "
                    "to decide what to click or fill next. Use it before acting in an app you do not know.",
        run=look,
        parameters={},
        priority=50,
    ),
    Command(
        name="click_element",
        description="Click a button, link, tab, menu item or row of the active window by its visible name.",
        run=click_element,
        patterns=[r"^(?:clique|clic|cliquer|appuie|appuyer|click|press)\s+(?:sur |on )?(?:le |la |l'|les |the )?(?:bouton |button |onglet |lien )?(?P<name>.{2,40})$"],
        parameters={"name": {"type": "string", "description": "Visible name of the element"}},
        required=["name"],
        priority=73,
    ),
    Command(
        name="fill_field",
        description="Type text into a field of the active window, found by its name or placeholder "
                    "(empty field name = the first field).",
        run=fill_field,
        parameters={"field": {"type": "string"}, "text": {"type": "string"}},
        required=["text"],
        priority=50,
    ),
]
