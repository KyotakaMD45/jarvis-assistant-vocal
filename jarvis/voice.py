"""Voice assistant loop: wake word -> speech-to-text -> local command or AI -> speech.

Each sentence first goes to the command registry (instant, free). If no command matches,
it goes to the AI, which may answer or call a command as a tool. The HUD (if any) is
updated through `self.ui`; commands typed in the HUD follow the same path.
"""
from __future__ import annotations

import itertools
import queue
import socket
import sys
import threading
import time
from collections.abc import Callable

from jarvis import commands
from jarvis.audio_out import play_fx
from jarvis.brain import Brain, BrainError
from jarvis.logger import get_logger
from jarvis.stt import Listener, MicError
from jarvis.textnorm import simple
from jarvis.tts import Speaker
from jarvis.ui import Ui

log = get_logger(__name__)

# What Jarvis *says* (French); the console/HUD shows the detailed English message.
SPOKEN = {
    "online": "Jarvis en ligne.",
    "no_mic": "Je n'ai pas accès au micro. Vous pouvez taper vos commandes.",
    "mic_lost": "J'ai perdu le micro. J'essaie de le reconnecter.",
    "auth": "La clé d'accès de l'intelligence artificielle n'est pas valide. Lancez le test pour plus de détails.",
    "connection": "Je n'arrive pas à joindre mon serveur. Vérifiez la connexion internet.",
    "timeout": "Le serveur met trop de temps à répondre. Réessayez dans un instant.",
    "limit": "Le compte de l'intelligence artificielle a atteint sa limite ou n'a plus de crédit.",
    "server": "Le service d'intelligence artificielle est momentanément surchargé. Réessayez dans un instant.",
    "refusal": "Je ne peux pas répondre à cette demande.",
    "not_found": "Le modèle configuré n'existe pas. Lancez le test pour voir les modèles disponibles.",
    "bad_tool": "Je n'ai pas compris quelle action faire. Pouvez-vous reformuler ?",
    "generic": "Une erreur est survenue. Les détails sont dans le journal.",
    "unknown_tool": "Je n'ai pas pu exécuter cette action.",
}
_ERROR_TO_SPOKEN = {
    "no_key": "auth", "bad_key_format": "auth", "auth": "auth", "permission": "auth",
    "connection": "connection", "timeout": "timeout", "rate_limit": "limit", "billing": "limit",
    "server": "server", "refusal": "refusal", "not_found": "not_found", "bad_tool": "bad_tool",
}
BARGE_WORDS = {"stop", "arrete", "attends", "attend", "tais", "pause", "silence", "non", "jarvis"}
YES = {"oui", "ouais", "oui oui", "oui vas y", "oui vas-y", "vas y", "vas-y", "confirme", "je confirme", "d'accord",
       "d accord", "ok", "okay", "exactement", "bien sur", "affirmatif", "oui s'il te plait", "oui merci", "c'est ca"}


def spoken_error(err: BrainError) -> str:
    return SPOKEN[_ERROR_TO_SPOKEN.get(err.kind, "generic")]


def _internet_ok() -> bool:
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=3).close()
        return True
    except OSError:
        return False


class VoiceAssistant:
    def __init__(self, cfg: dict, brain: Brain, config_warnings: list[str], ui: Ui | None = None):
        self.cfg = cfg
        self.brain = brain
        self.config_warnings = config_warnings
        self.ui = ui or Ui()
        self.speaker = Speaker(cfg)
        # Keep the red "error" orb while an error message is spoken.
        self.speaker.on_audio_start = lambda: self._state != "error" and self._set_state("speaking")
        self.listener = Listener(cfg)
        self.follow_up_seconds = float(cfg["listening"]["follow_up_seconds"])
        self.wake_sound = cfg["listening"]["wake_sound"]
        self.sounds = cfg["hud"]["sounds"]
        self.use_tools = cfg["ai"]["use_tools"]
        self.mic_ok = False
        self.listening_enabled = True
        self.reminders = None                      # ReminderService, set by the runtime
        self.notify: Callable[[str, str], None] = lambda title, text: None
        # Window/app control, set by the runtime (no-ops in console mode).
        self.on_show_hud: Callable[[], None] = lambda: None
        self.on_hide_hud: Callable[[], None] = lambda: None
        self.on_minimize_hud: Callable[[], None] = lambda: None
        self.on_quit: Callable[[], None] = lambda: None
        self.on_restart: Callable[[], None] = lambda: None
        self.on_listening_changed: Callable[[], None] = lambda: None
        self._state = "boot"
        self._typed: queue.Queue[str] = queue.Queue()
        self._announcements: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._exit_action: str | None = None       # "quit" / "restart" after the current answer
        self._push_to_talk = threading.Event()     # mic button / Space in the HUD
        self._pending_command: str | None = None   # what the user said while interrupting Jarvis
        self._last_answer = ""                     # for the REPEAT button
        self._alternative: str | None = None       # offline transcript of the current sentence
        self.barge_in = cfg["listening"]["barge_in"]
        self._ids = itertools.count(1)

    # -- control from other threads (HUD, tray, reminders) -----------------------------
    def submit_text(self, text: str) -> None:
        """A command typed in the HUD."""
        self._typed.put(text)

    def announce(self, text: str) -> None:
        """Say something as soon as possible (reminders). Also shown as a notification."""
        self._announcements.put(text)
        self.notify("Jarvis", text)

    def request_stop(self) -> None:
        self._stop.set()
        self.speaker.stop()

    def request_quit(self) -> None:
        self._exit_action = "quit"

    def request_restart(self) -> None:
        self._exit_action = "restart"

    def show_hud(self) -> None:
        self.on_show_hud()

    def hide_hud(self) -> None:
        self.on_hide_hud()

    def toggle_listening(self) -> None:
        self.set_listening(not self.listening_enabled)

    def listen_now(self) -> None:
        """Push-to-talk (HUD mic button / Space): listen right away, no wake word needed."""
        if not self.mic_ok:
            self.ui.log("system", "No microphone: type your command in SYS.")
            return
        if not self.listening_enabled:
            self.set_listening(True)
        self.speaker.stop()  # also interrupts Jarvis if he is talking
        self._push_to_talk.set()

    def avatar_look(self, direction: str) -> None:
        self.ui.look(direction)

    def repeat_last(self) -> None:
        self._announcements.put(self._last_answer or "Je n'ai encore rien dit.")

    def handle_action(self, name: str, value: str = "") -> None:
        """Buttons of the HUD."""
        log.info("HUD action %s %r", name, value)
        if name == "listen":
            self.listen_now()
        elif name == "repeat":
            self.repeat_last()
        elif name == "media":
            from jarvis.winctl import press_key

            press_key("play_pause")
            self.ui.log("system", "Media: play / pause")
        elif name == "toggle_listening":
            self.toggle_listening()
        elif name == "voice_test":
            self.submit_text("test vocal")
        elif name == "switch_ai" and value in ("claude", "groq", "gemini", "openai"):
            self.submit_text(f"passe sur {value}")
        elif name == "open_config":
            import os

            from jarvis.paths import CONFIG_PATH

            self.on_minimize_hud()
            os.startfile(str(CONFIG_PATH))  # noqa: S606 - our own config file
        else:
            log.warning("Unknown HUD action %r", name)

    def set_listening(self, enabled: bool) -> None:
        self.listening_enabled = enabled
        if self.mic_ok:
            self.ui.status(mic="ACTIVE" if enabled else "PAUSED")
        self._set_state("idle" if enabled else "paused")
        self.ui.log("system", "Microphone listening resumed." if enabled else "Microphone paused (tray icon > Écoute active).")
        self.on_listening_changed()

    def _interrupted(self) -> bool:
        return (self._stop.is_set() or not self._typed.empty() or not self._announcements.empty()
                or not self.listening_enabled or self._push_to_talk.is_set())

    # -- HUD helpers ---------------------------------------------------------------------
    def _set_state(self, state: str) -> None:
        self._state = state
        self.ui.state(state)

    def _level_pump(self) -> None:
        """Send the microphone/voice level to the HUD ~15 times per second."""
        last = 0.0
        while not self._stop.is_set():
            if self._state == "speaking":
                value = self.speaker.level
            elif self._state == "listening":
                value = self.listener.level
            else:
                value = 0.0
            if abs(value - last) > 0.03 or (value == 0.0 and last != 0.0):
                self.ui.level(value)
                last = value
            time.sleep(1 / 15)

    @staticmethod
    def _status_line(text: str) -> None:
        try:
            sys.stdout.write("\r" + text[:100].ljust(100) + "\r")
            sys.stdout.flush()
        except (AttributeError, OSError, ValueError):
            pass  # no console (background mode)

    def _on_partial(self, text: str) -> None:
        self._status_line(f"  ... {text}")
        self.ui.partial(text)

    def _on_wake(self, early: bool) -> None:
        # Open the voice connection and the AI client while the user is still talking.
        self.speaker.prewarm()
        threading.Thread(target=self.brain.warm_up, daemon=True).start()
        self._set_state("listening")
        if not early and self.wake_sound:
            play_fx("wake")
        self._status_line("  [listening...]")

    def _voice_status(self) -> str:
        if self.speaker._edge is None:
            return "OFFLINE VOICE"
        name = self.cfg["voice"]["voice"].split("-")[-1].replace("Neural", "").upper()
        return f"EDGE · {name}" if self.speaker.edge_usable() else "OFFLINE VOICE"

    def _ai_status(self) -> str:
        return f"{self.brain.label.upper()} · {self.brain.model}"

    # -- speaking / asking ---------------------------------------------------------------
    def say(self, text: str) -> None:
        self._last_answer = text
        print(f"{self.cfg['assistant_name']} > {text}")
        self.ui.log("jarvis", text)
        self.speaker.speak(text)

    def ask_yes_no(self, question: str) -> bool:
        """Ask a question and wait for "oui" (spoken, or typed in the HUD)."""
        self.say(question)
        answer = None
        if self.mic_ok and self.listening_enabled:
            self._set_state("listening")
            self.listener.unmute()
            try:
                answer = self.listener.listen(require_wake=False, timeout=7, on_partial=self._on_partial,
                                              should_stop=lambda: self._stop.is_set() or not self._typed.empty())
            finally:
                self.listener.mute()
        if answer is None:
            try:
                answer = self._typed.get(timeout=0.1 if self.mic_ok else 10)
            except queue.Empty:
                answer = ""
        print(f"You > {answer}")
        self.ui.log("user", answer or "(pas de réponse)")
        self._set_state("thinking")
        return simple(answer) in YES or simple(answer).startswith("oui")

    def voice_test(self) -> None:
        v = self.cfg["voice"]
        print(f"Voice test: voice={v['voice']} pitch={v['pitch']} rate={v['rate']} (edit them in config.json)")
        self.ui.log("system", f"Voice test: {v['voice']}, pitch {v['pitch']}, rate {v['rate']}")
        self.ui.log("jarvis", v["test_sentence"])
        engine = self.speaker.speak(v["test_sentence"])
        print(f"  engine={engine}, first audio after {self.speaker.first_audio_delay or 0:.2f}s")

    def _context(self, from_ai: bool = False) -> commands.CommandContext:
        return commands.CommandContext(cfg=self.cfg, say=self.say, ask_yes_no=self.ask_yes_no, assistant=self,
                                       brain=self.brain, reminders=self.reminders, notify=self.notify,
                                       from_ai=from_ai)

    # Commands that open a window: the HUD steps aside, otherwise Windows (which does not let a
    # background program take the foreground) leaves the new window hidden behind it.
    OPENS_WINDOW = {"open_app", "open_website", "web_search", "play_music", "windows_settings", "search_files"}

    def _run_command(self, command: commands.Command, args: dict, from_ai: bool = False) -> None:
        if command.name in self.OPENS_WINDOW:
            from jarvis import pcctl

            pcctl.mark_app_opened()  # so that a following "type_text" waits for the new window
        result = commands.execute(command, args, self._context(from_ai))
        log.info("Command %s -> %r", command.name, result)
        if command.name in self.OPENS_WINDOW and result and not result.startswith(("Je n'ai pas", "Désolé")):
            self.on_minimize_hud()
        if result:
            self.say(result)
        if command.name == "switch_ai":
            self.ui.status(model=self._ai_status())

    def ask_ai(self, text: str, alternative: str | None = None) -> bool:
        """Stream the AI's answer to the speaker and the HUD; run the commands it asks for."""
        entry = f"j{next(self._ids)}"
        print(f"{self.cfg['assistant_name']} > ", end="", flush=True)
        started = time.perf_counter()
        first = True
        tools = commands.tool_specs() if self.use_tools else None
        spoken: list[str] = []
        spoken_words: set[str] = set()

        def on_text(chunk: str) -> None:
            nonlocal first
            if first:
                first = False
                self.ui.log("jarvis", "", entry, streaming=True)
                if self.sounds:
                    play_fx("reply")
            print(chunk, end="", flush=True)
            spoken.append(chunk)
            spoken_words.update(simple(chunk).split())
            self.ui.log_append(entry, chunk)

        # Barge-in: while Jarvis talks, the microphone keeps listening; if the user speaks
        # (words that are not Jarvis's own voice coming back), Jarvis stops and listens.
        barge: dict = {}
        monitor_stop = threading.Event()

        def is_echo(words: list[str]) -> bool:
            ws = [w for w in (simple(x) for x in words) if w]
            if not ws:
                return True
            if any(w in self.listener.wake_words or w in BARGE_WORDS for w in ws) and \
                    not all(w in spoken_words for w in ws):
                return False
            if len(ws) < 3:
                return True
            unknown = sum(1 for w in ws if w not in spoken_words)
            return unknown / len(ws) < 0.6

        def on_trigger() -> None:
            barge["hit"] = True
            self.speaker.stop()
            self._set_state("listening")

        monitor = None
        if self.barge_in and self.mic_ok and self.listening_enabled:
            monitor = threading.Thread(
                target=lambda: barge.update(text=self.listener.monitor_barge_in(monitor_stop, is_echo, on_trigger)),
                name="barge-in", daemon=True)
            monitor.start()

        try:
            try:
                prompt = text if not alternative else f"{text}\n(autre transcription possible : « {alternative} »)"
                self.speaker.speak_stream(self.brain.ask(prompt, tools=tools), on_text=on_text)
            finally:
                monitor_stop.set()
                if monitor is not None:
                    monitor.join(12 if barge.get("hit") else 3)
            print()
            if spoken:
                self._last_answer = "".join(spoken).strip()
            if barge.get("hit"):
                log.info("Jarvis was interrupted; user said %r", barge.get("text"))
                if barge.get("text"):
                    self._pending_command = barge["text"]
                return True
            delay = self.speaker.first_audio_delay
            if delay:
                log.info("Voice answer: first audio %.2fs after the command was recognized", delay)
            for call in self.brain.last_tool_calls:
                command = commands.get(call.name)
                if command is None or not command.ai_tool:
                    log.error("AI asked for unknown tool %r", call.name)
                    self.say(SPOKEN["unknown_tool"])
                    continue
                try:
                    args = commands.validate_args(command, call.args)
                except ValueError as exc:
                    log.error("Invalid tool arguments for %s: %s (%r)", call.name, exc, call.args)
                    self.say(SPOKEN["bad_tool"])
                    continue
                self.ui.log("system", f"Action: {command.name} {args}")
                self._run_command(command, args, from_ai=True)
            self.ui.status(network="ONLINE", voice=self._voice_status())
            return True
        except BrainError as err:
            print(f"\n[!] {err.message}")
            self._set_state("error")
            self.ui.log("system", err.message)
            if err.kind in ("connection", "timeout"):
                self.ui.status(network="ONLINE" if _internet_ok() else "OFFLINE")
            if self.sounds:
                play_fx("error", wait=True)
            self.speaker.speak(spoken_error(err))
        except Exception:  # noqa: BLE001 - never crash the voice loop
            log.exception("Unexpected error while answering")
            print("\n[!] Unexpected error. Details in jarvis.log.")
            self._set_state("error")
            self.ui.log("system", "Unexpected error. Details in jarvis.log.")
            self.speaker.speak(SPOKEN["generic"])
        finally:
            if not first:
                self.ui.log_end(entry)
            log.info("Voice turn total %.2fs", time.perf_counter() - started)
        return False

    def handle(self, text: str) -> str:
        """Run one sentence. Returns "follow_up" (keep listening briefly) or "idle"."""
        found = commands.match(text)
        if found is None and self._alternative and len(text.split()) <= 3:
            # Whisper sometimes garbles a very short command ("copie ça" -> "PISA") that the offline
            # model heard correctly: if only the offline version is a known command, use it.
            found = commands.match(self._alternative)
            if found is not None:
                log.info("Using the offline transcript %r instead of %r", self._alternative, text)
                text = self._alternative
        if found is not None:
            try:
                self._run_command(found.command, found.args)
            except commands.Unsure:
                log.info("Local command %s unsure, asking the AI: %r", found.command.name, text)
                return "follow_up" if self.ask_ai(text, self._alternative) else "idle"
            # A conversation-like command (time, battery...) may get a follow-up question.
            return "follow_up" if found.command.name not in ("cancel", "quit_jarvis", "restart_jarvis") else "idle"
        return "follow_up" if self.ask_ai(text, self._alternative) else "idle"

    # -- startup -------------------------------------------------------------------------
    def _boot(self) -> None:
        """Load everything, reporting each step to the console and the HUD boot screen."""
        words = ", ".join(w.upper() for w in self.cfg["listening"]["wake_words"])
        self.ui.status(mode="VOICE", model=self._ai_status(), wake=words, mic="STARTING", voice="CONNECTING")
        print("Loading the speech model...")
        threading.Thread(target=self.brain.warm_up, daemon=True).start()
        voice_ready: dict = {}
        voice_thread = threading.Thread(target=lambda: voice_ready.update(ok=self.speaker.prewarm(wait=True)), daemon=True)
        voice_thread.start()
        commands.load_commands()
        from jarvis.app_index import INDEX

        INDEX.load_async()

        if self.cfg["listening"]["cloud_transcription"] == "groq":
            from jarvis.cloud_stt import GroqWhisper

            whisper = GroqWhisper(self.cfg)
            if whisper.available():
                self.listener.transcriber = whisper
                threading.Thread(target=whisper.warm_up, daemon=True).start()
        started = time.perf_counter()
        try:
            self.listener.open()
            self.mic_ok = True
            self.ui.boot(f"Speech recognition online ({time.perf_counter() - started:.1f}s)")
            self.ui.boot("Microphone active")
            if self.listener.transcriber is not None:
                self.ui.boot("Cloud speech recognition: Groq Whisper")
            else:
                self.ui.boot("Cloud speech recognition off (no Groq key): offline model only", ok=False)
            self.ui.status(mic="ACTIVE")
        except MicError as err:
            print(f"[!] {err}")
            self.ui.boot(f"Microphone: {err}", ok=False)
            self.ui.log("system", f"{err} You can type commands below.")
            self.ui.status(mic="UNAVAILABLE", mode="TYPED")

        self.ui.boot(f"{len(commands.load_commands())} commands loaded")
        online = _internet_ok()
        self.ui.status(network="ONLINE" if online else "OFFLINE")
        voice_thread.join(10)
        if voice_ready.get("ok"):
            self.ui.boot("Voice synthesis link established")
        else:
            self.ui.boot("Neural voice unavailable, offline voice ready", ok=False)
        self.ui.status(voice=self._voice_status())

        from jarvis.api_key import get_api_key, looks_like_key

        key, _ = get_api_key(self.brain.provider_name)
        if key and looks_like_key(key, self.brain.provider_name):
            self.ui.boot(f"AI core linked ({self._ai_status()})")
        else:
            self.ui.boot(f"AI core: {self.brain.label} API key missing (start.bat --setup-key {self.brain.provider_name})", ok=False)
            self.ui.log("system", f"No valid {self.brain.label} API key. Run start.bat --setup-key {self.brain.provider_name}.")

        words_console = ", ".join(f"'{w}'" for w in self.cfg["listening"]["wake_words"])
        print(f"{self.cfg['assistant_name']} online (voice mode). Say {words_console} then your request. "
              "Say 'que sais-tu faire' for help, 'au revoir' to quit.")
        self.ui.ready()
        self._set_state("idle")
        if self.sounds:
            play_fx("startup", wait=True)

    # -- main loop -----------------------------------------------------------------------
    def _next_input(self, follow_up: bool) -> tuple[str, str] | None:
        """Wait for the next announcement, typed or spoken command: (kind, text)."""
        self._alternative = None
        self.listener.last_alternative = None
        item = self._next_input_raw(follow_up)
        if item is not None and item[0] == "command":
            self._alternative = self.listener.last_alternative
        return item

    def _next_input_raw(self, follow_up: bool) -> tuple[str, str] | None:
        if self._pending_command:
            text, self._pending_command = self._pending_command, None
            return "command", text
        if not self._announcements.empty():
            return "announce", self._announcements.get_nowait()
        if not self._typed.empty():
            return "command", self._typed.get_nowait()
        if self._push_to_talk.is_set() and self.mic_ok:
            self._push_to_talk.clear()
            if self.wake_sound:
                play_fx("wake")
            self._set_state("listening")
            text = self.listener.listen(require_wake=False, timeout=8, on_partial=self._on_partial,
                                        should_stop=lambda: self._stop.is_set() or not self._typed.empty())
            return ("command", text) if text else None
        if not self.mic_ok or not self.listening_enabled:
            time.sleep(0.3)
            return None
        words = ", ".join(f"'{w}'" for w in self.cfg["listening"]["wake_words"])
        if follow_up:
            self._set_state("listening")
            self._status_line(f"  [listening for a follow-up, {self.follow_up_seconds:.0f}s...]")
            text = self.listener.listen(require_wake=False, timeout=self.follow_up_seconds,
                                        on_partial=self._on_partial, should_stop=self._interrupted)
            if text and self._is_filler(text):
                # "ok", "ouais je vois", "merci"... said to Jarvis or to someone else: end the follow-up.
                log.info("Follow-up ignored (filler): %r", text)
                return None
        else:
            self._set_state("idle")
            self._status_line(f"  [waiting for {words}]")
            text = self.listener.listen(on_wake=self._on_wake, on_partial=self._on_partial,
                                        should_stop=self._interrupted)
        return ("command", text) if text else None

    FILLERS = {"ok", "okay", "oui", "ouais", "ouai", "non", "d accord", "merci", "merci beaucoup", "hum", "hmm", "ah",
               "oh", "bon", "bah", "ben", "je vois", "ouais je vois", "oui je vois", "c est bon", "super", "cool",
               "parfait", "genial", "tres bien", "bien", "ok merci", "d accord merci", "voila", "euh", "hein", "quoi",
               "ok d accord", "oui oui", "ouais ouais", "c est ca", "exactement", "oui je vois je vois"}

    def _is_filler(self, text: str) -> bool:
        return simple(text) in self.FILLERS or simple(text).replace(" ", "") in {f.replace(" ", "") for f in self.FILLERS}

    def _reopen_microphone(self) -> None:
        self.listener.close()
        while not self._stop.is_set():
            time.sleep(3)
            try:
                self.listener.open()
                print("Microphone reconnected.")
                self.ui.status(mic="ACTIVE")
                self.ui.log("system", "Microphone reconnected.")
                return
            except MicError as err:
                self._status_line(f"  [!] {err} (retrying...)")
                if not self._typed.empty() or not self._announcements.empty():
                    return  # serve typed commands and reminders meanwhile

    def run(self) -> int:
        """Returns the exit code, or -1 when there is no microphone and no HUD to type in."""
        threading.Thread(target=self._level_pump, name="level-pump", daemon=True).start()
        self._boot()
        if not self.mic_ok and not self.ui.enabled:
            self.speaker.speak(SPOKEN["no_mic"].split(".")[0] + ".")
            return -1
        self.say(SPOKEN["online"] if self.mic_ok else SPOKEN["no_mic"])

        follow_up = False
        while not self._stop.is_set():
            try:
                item = self._next_input(follow_up)
            except MicError as err:
                print(f"\n[!] {err}")
                self.ui.status(mic="LOST")
                self.ui.log("system", str(err))
                self.speaker.speak(SPOKEN["mic_lost"])
                self._reopen_microphone()
                follow_up = False
                continue
            except KeyboardInterrupt:
                print("\nGoodbye.")
                return 0

            if self._stop.is_set():
                break
            if item is None:
                follow_up = False
                if not self.listening_enabled and self._state != "paused":
                    self._set_state("paused")
                continue
            kind, text = item
            text = text.strip()
            if not text:
                continue
            self._status_line("")
            self.ui.partial("")
            self.listener.mute()
            if self.mic_ok:
                self.ui.status(mic="MUTED")
            try:
                if kind == "announce":
                    if self.sounds:
                        play_fx("wake", wait=True)
                    self._set_state("speaking")
                    self.say(text)
                    result = "idle"
                else:
                    print(f"You > {text}")
                    self.ui.log("user", text)
                    self._set_state("thinking")
                    result = self.handle(text)
            except KeyboardInterrupt:
                self.speaker.stop()
                print("\n[interrupted]")
                result = "idle"
            finally:
                self.listener.unmute()
                if self.mic_ok:
                    self.ui.status(mic="ACTIVE" if self.listening_enabled else "PAUSED")
            if self._exit_action == "quit":
                self.on_quit()
                return 0
            if self._exit_action == "restart":
                self.on_restart()
                return 0
            follow_up = result == "follow_up" and self.follow_up_seconds > 0 and self.mic_ok and self.listening_enabled
        return 0

    def close(self) -> None:
        self._stop.set()
        self.listener.close()
        self.speaker.close()


def run_voice_mode(cfg: dict, config_warnings: list[str]) -> int:
    """Console-only voice mode (no tray, no HUD). Returns -1 when voice mode is unavailable."""
    from jarvis.reminders import ReminderService

    assistant = VoiceAssistant(cfg, Brain(cfg), config_warnings)
    assistant.reminders = ReminderService(on_due=assistant.announce)
    assistant.reminders.start()
    try:
        return assistant.run()
    finally:
        assistant.reminders.stop()
        assistant.close()
