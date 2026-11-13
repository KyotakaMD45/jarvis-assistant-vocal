"""Entry point.

Default: background mode (voice + HUD window + tray icon). Other modes: --text (keyboard),
--no-hud (voice without window), --test, --setup-key [provider], --quit/--show/--restart
(control the running instance).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading

from jarvis.config import load_config
from jarvis.logger import get_logger, setup_logging

log = get_logger("jarvis")

HELP_TEXT = """Commands:
  test        check internet, AI keys, models, microphone and speaker
  voice test  play a sample sentence with the voice settings from config.json
  reset       forget the current conversation
  help        show this help
  exit        quit Jarvis
Anything else: a Jarvis command (e.g. "ouvre le bloc-notes", "volume à 30") or a question."""


def _configure_console() -> None:
    # pythonw (background mode) has no console: give print() a harmless target.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    # Make accents display correctly in the Windows console.
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _voice_test(cfg: dict) -> None:
    from jarvis.tts import Speaker

    v = cfg["voice"]
    print(f"Voice test: voice={v['voice']} pitch={v['pitch']} rate={v['rate']} (edit them in config.json)")
    speaker = Speaker(cfg)
    try:
        engine = speaker.speak(v["test_sentence"])
        print(f"  engine={engine}, first audio after {speaker.first_audio_delay or 0:.2f}s")
    finally:
        speaker.close()


def chat_loop(cfg: dict, config_warnings: list[str]) -> int:
    """Keyboard mode: same commands and AI as voice mode, answers printed (not spoken)."""
    from jarvis import commands
    from jarvis.brain import Brain, BrainError
    from jarvis.diagnostics import run_diagnostics
    from jarvis.reminders import ReminderService

    brain = Brain(cfg)
    threading.Thread(target=brain.warm_up, name="warm-up", daemon=True).start()
    reminders = ReminderService(on_due=lambda text: print(f"\n[REMINDER] {text}\nYou > ", end="", flush=True))
    reminders.start()
    from jarvis.app_index import INDEX

    INDEX.load_async()
    name = cfg.get("assistant_name", "Jarvis")

    def ask_yes_no(question: str) -> bool:
        print(f"{name} > {question}")
        try:
            return input("You > ").strip().lower().startswith(("o", "y"))
        except EOFError:
            return False

    ctx = commands.CommandContext(cfg=cfg, say=lambda text: print(f"{name} > {text}"), ask_yes_no=ask_yes_no,
                                  brain=brain, reminders=reminders)
    print(f"{name} online ({brain.label}). Type a message, 'help' for commands, 'exit' to quit.")
    for warning in config_warnings:
        print(f"  warning: {warning}")

    while True:
        try:
            user_text = input("\nYou > ").replace("﻿", "").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0
        lowered = user_text.lower()
        if not lowered:
            continue
        if lowered in {"exit", "quit", "bye"}:
            print("Goodbye.")
            return 0
        if lowered == "help":
            print(HELP_TEXT)
            continue
        if lowered == "test":
            run_diagnostics(cfg, config_warnings)
            continue
        found = commands.match(user_text)
        if found is not None:
            if found.command.name == "quit_jarvis":
                print(f"{name} > Au revoir, monsieur.")
                return 0
            if found.command.name == "voice_test":
                _voice_test(cfg)
                continue
            try:
                result = commands.execute(found.command, found.args, ctx)
            except commands.Unsure:
                result = None
                found = None
            if found is not None:
                if result:
                    print(f"{name} > {result}")
                continue
        print(f"{name} > ", end="", flush=True)
        try:
            for chunk in brain.ask(user_text, tools=commands.tool_specs() if cfg["ai"]["use_tools"] else None):
                print(chunk, end="", flush=True)
            print()
            for call in brain.last_tool_calls:
                command = commands.get(call.name)
                if command is None:
                    print(f"[!] Unknown action {call.name}")
                    continue
                try:
                    args = commands.validate_args(command, call.args)
                except ValueError as exc:
                    print(f"[!] Invalid action arguments: {exc}")
                    continue
                ctx.from_ai = True
                try:
                    result = commands.execute(command, args, ctx)
                finally:
                    ctx.from_ai = False
                if result:
                    print(f"{name} > {result}")
        except BrainError as err:
            print(f"\n[!] {err.message}")
        except KeyboardInterrupt:
            print("\n[interrupted]")
        except Exception as exc:  # noqa: BLE001 - last safety net, never crash
            log.exception("Unexpected error in chat loop")
            print(f"\n[!] Unexpected error ({exc.__class__.__name__}). Details in jarvis.log.")


def _install_crash_logging() -> None:
    """Native crashes (no Python traceback) are written to crash.log; thread errors to jarvis.log."""
    import faulthandler
    import threading

    from jarvis.paths import ROOT

    try:
        crash_file = open(ROOT / "crash.log", "a", encoding="utf-8")  # noqa: SIM115 - kept open on purpose
        crash_file.write(f"\n--- Apex started (pid {os.getpid()}) ---\n")
        crash_file.flush()
        faulthandler.enable(file=crash_file, all_threads=True)
    except OSError:
        pass

    def thread_hook(args) -> None:
        log.error("Uncaught error in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = thread_hook


def run_background(cfg: dict, warnings: list[str], use_hud: bool, start_hidden: bool, wait_pid: int | None) -> int:
    from jarvis.instance import InstanceLock, send_command, wait_for_process_exit
    from jarvis.runtime import Runtime

    if wait_pid:
        wait_for_process_exit(wait_pid)  # restart: let the old instance release the microphone
    lock = InstanceLock()
    acquired = lock.acquire_waiting(20) if wait_pid else lock.acquire()
    if not acquired:
        shown = send_command("show")
        print("Jarvis is already running" + (" - its window was brought back." if shown else "."))
        log.info("Second launch: Jarvis already running (show sent: %s)", shown)
        return 0
    _install_crash_logging()
    code = Runtime(cfg, warnings, use_hud=use_hud, instance=lock, start_hidden=start_hidden).run()
    # Everything is closed at this point. Skip the interpreter teardown: pythonnet's exit hook
    # (used by the window) can keep one CPU core busy for ~15 s.
    logging.shutdown()
    try:
        sys.stdout.flush()
    except (OSError, ValueError):
        pass
    os._exit(code)


def main(argv: list[str] | None = None) -> int:
    _configure_console()
    parser = argparse.ArgumentParser(prog="jarvis", description="Jarvis voice assistant")
    parser.add_argument("--test", action="store_true", help="check internet, AI keys, microphone and speaker, then exit")
    parser.add_argument("--setup-key", nargs="?", const="claude", metavar="PROVIDER",
                        help="enter or replace an API key: claude (default), groq, gemini or openai")
    parser.add_argument("--setup-key-if-missing", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--setup-model", action="store_true", help="download the speech model if missing")
    parser.add_argument("--text", action="store_true", help="keyboard mode in the console")
    parser.add_argument("--voice-test", action="store_true", help="play the test sentence and exit")
    parser.add_argument("--no-hud", action="store_true", help="voice + tray icon, without the HUD window")
    parser.add_argument("--hidden", action="store_true", help="start in the tray with the window hidden")
    parser.add_argument("--quit", action="store_true", help="stop the running Jarvis")
    parser.add_argument("--show", action="store_true", help="show the running Jarvis window")
    parser.add_argument("--restart", action="store_true", help="restart the running Jarvis")
    parser.add_argument("--wait-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--console", action="store_true", help="run in this console window (see the logs live)")
    args = parser.parse_args(argv)

    if args.quit or args.show or args.restart:
        from jarvis.instance import send_command

        cmd = "quit" if args.quit else "show" if args.show else "restart"
        ok = send_command(cmd)
        print(f"Jarvis: '{cmd}' sent." if ok else "Jarvis is not running.")
        return 0 if ok else 1

    cfg, warnings = load_config()
    setup_logging(cfg.get("log_level", "INFO"))
    # Warnings were produced before logging was ready: record them now.
    for warning in warnings:
        log.warning(warning)
    log.info("Jarvis starting (args=%s)", vars(args))

    try:
        if args.setup_key or args.setup_key_if_missing:
            from jarvis.key_setup import setup_key
            return setup_key(cfg, provider=(args.setup_key or "claude").lower(), only_if_missing=args.setup_key_if_missing)
        if args.test:
            from jarvis.diagnostics import run_diagnostics
            return run_diagnostics(cfg, warnings)
        if args.setup_model:
            from jarvis.setup_model import ensure_model
            return ensure_model(cfg)
        if args.voice_test:
            _voice_test(cfg)
            return 0
        if args.text:
            return chat_loop(cfg, warnings)
        use_hud = cfg["hud"]["enabled"] and not args.no_hud
        return run_background(cfg, warnings, use_hud=use_hud, start_hidden=args.hidden, wait_pid=args.wait_pid)
    except Exception:  # noqa: BLE001
        log.exception("Fatal error")
        print("[!] Jarvis hit an unexpected error. Details in jarvis.log.")
        return 1
