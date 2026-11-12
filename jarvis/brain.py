"""The AI brain: one conversation, several possible providers (Claude, Groq, Gemini, OpenAI).

`ask()` streams the answer text. When the AI decides to run a command instead (tool call),
the calls are left in `last_tool_calls` for the caller to execute.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import datetime

from jarvis.api_key import get_api_key, looks_like_key
from jarvis.logger import get_logger
from jarvis.providers import PROVIDERS, create
from jarvis.providers.base import BrainError, ToolCall
from jarvis.state import load_state, save_state

log = get_logger(__name__)

__all__ = ["Brain", "BrainError", "ToolCall"]

SPEECH_PROMPT = (
    "\n\nLes messages de l'utilisateur viennent d'une reconnaissance vocale qui peut se tromper : homophones "
    "(« mais » pour « mets », « sa » pour « ça », « l'anglais » pour « l'onglet »), mots coupés, noms déformés "
    "(« Chad JPT » pour ChatGPT, « viscose » pour VS Code), ponctuation absente. Comprends l'intention la plus "
    "probable en t'aidant de la conversation précédente et de la fenêtre active. Si une « autre transcription » "
    "est fournie, choisis la version la plus plausible. Si l'utilisateur se corrige (« non, je voulais dire… », "
    "« pas ça »), applique la correction à sa demande précédente. Une phrase courte qui suit ta réponse est souvent "
    "la suite de la même conversation. Si la demande reste vraiment ambiguë, pose une seule question courte "
    "au lieu de deviner. Ne parle jamais de reconnaissance vocale ni d'erreurs de transcription."
)


def _active_window_title() -> str:
    """Title of the window the user works in (helps with "écris ici", "ferme ça"); "" if unknown."""
    try:
        from jarvis import pcctl

        hwnd = pcctl.target_window()
        return pcctl.window_info(hwnd)[1][:90] if hwnd else ""
    except Exception:  # noqa: BLE001 - context only, never fail a request for it
        return ""

TOOLS_PROMPT = (
    "\n\nTu contrôles l'ordinateur Windows de l'utilisateur grâce aux outils fournis. "
    "Si la demande correspond à un outil, appelle-le directement sans écrire de texte : "
    "l'outil annonce lui-même le résultat. N'invente jamais qu'une action a été faite sans appeler l'outil. "
    "Tu peux appeler plusieurs outils à la suite : par exemple, pour écrire du code dans VS Code, appelle "
    "open_app (VS Code), puis keyboard_shortcut (new), puis type_text avec le code complet. Pour écrire un "
    "texte, un mail ou du code demandé par l'utilisateur, rédige-le toi-même et passe-le à type_text. "
    "Pour « ce texte », « ça », « la sélection » (résumer, traduire, corriger, reformuler, expliquer), utilise "
    "selected_text. Pour envoyer un message (WhatsApp ou mail), utilise send_message : l'utilisateur confirmera. "
    "Pour « demande à Claude / ChatGPT / Perplexity », utilise ask_web_ai. "
    "Tu utilises le PC comme son propriétaire le ferait, comme un humain : pour agir dans une application "
    "(boutons, menus, champs), regarde d'abord avec screen_look, puis utilise click_element et fill_field. "
    "N'appuie jamais sur une touche au hasard. Si aucune action ne permet de faire la demande (par exemple "
    "supprimer un message déjà envoyé), dis-le franchement en une phrase. "
    "Sinon, réponds normalement."
)


class Brain:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.ai = cfg["ai"]
        self.history: list[dict] = []
        self.last_tool_calls: list[ToolCall] = []
        saved = load_state().get("provider")
        self.provider_name = saved if saved in PROVIDERS else self.ai["provider"]
        self._providers: dict[str, tuple[str, object]] = {}  # name -> (key, provider)
        self._lock = threading.Lock()

    # -- providers -----------------------------------------------------------------------
    @property
    def label(self) -> str:
        return PROVIDERS[self.provider_name].label

    @property
    def model(self) -> str:
        section = self.ai.get(self.provider_name, {})
        return section.get("model", "")

    def _provider(self, name: str | None = None):
        name = name or self.provider_name
        info = PROVIDERS[name]
        key, source = get_api_key(name)
        if not key:
            raise BrainError("no_key", f"No {info.label} API key found. Run `start.bat --setup-key {name}` to add it ({info.keys_url}).")
        if not looks_like_key(key, name):
            raise BrainError("bad_key_format", f"The {info.label} API key from {source} does not look valid "
                                               f"(it should start with '{info.key_prefix}'). Re-enter it with `start.bat --setup-key {name}`.")
        with self._lock:
            cached = self._providers.get(name)
            if cached is None or cached[0] != key:
                cached = (key, self._create_with_retry(name, key))  # lazy SDK import happens here
                self._providers[name] = cached
            return cached[1]

    def _create_with_retry(self, name: str, key: str):
        """Windows Smart App Control sometimes refuses an unsigned SDK DLL once (failed online
        reputation check); the next attempt usually works."""
        for attempt in range(3):
            try:
                return create(name, self.ai, key)
            except (ImportError, OSError) as exc:
                log.warning("AI SDK import failed (attempt %d): %r", attempt + 1, exc)
                if attempt == 2:
                    raise BrainError("sdk_blocked", "Windows blocked a component of the AI library (Smart App Control "
                                                    "or antivirus). Try again in a moment; details in jarvis.log.") from exc
                time.sleep(1.0)
        raise AssertionError("unreachable")

    def warm_up(self) -> None:
        """Import the SDK and build the client ahead of time (run in a background thread)."""
        started = time.perf_counter()
        try:
            self._provider()
            log.info("Brain (%s) warmed up in %.1fs", self.provider_name, time.perf_counter() - started)
        except BrainError as err:
            log.warning("Warm-up skipped: %s", err.message)
        except Exception:  # noqa: BLE001 - warm-up must never crash anything
            log.exception("Warm-up failed")

    def switch(self, name: str) -> str:
        """Change the provider (persists in state.json). Returns the sentence to say."""
        info = PROVIDERS[name]
        if name == self.provider_name:
            return f"J'utilise déjà {info.label}."
        key, _ = get_api_key(name)
        if not key:
            return f"Je n'ai pas de clé pour {info.label}. Ajoutez-la avec start.bat, tiret tiret setup-key {name}."
        if not looks_like_key(key, name):
            return f"La clé {info.label} enregistrée semble invalide. Ressaisissez-la avec start.bat, tiret tiret setup-key {name}."
        self.provider_name = name
        save_state(provider=name)
        log.info("AI provider switched to %s (%s)", name, self.model)
        threading.Thread(target=self.warm_up, daemon=True).start()
        return f"C'est fait, j'utilise maintenant {info.label}."

    def complete(self, system: str, text: str) -> str:
        """One-shot answer (no tools, no conversation history): summaries, rewrites, translations."""
        try:
            provider = self._provider()
            return "".join(provider.stream(system, [{"role": "user", "content": text}], None)).strip()
        except Exception as exc:  # noqa: BLE001
            log.warning("Completion failed: %r", exc)
            return ""

    def translate(self, text: str, lang: str = "en") -> str:
        """Short spoken translation (used to say French action confirmations in English)."""
        cache = self.__dict__.setdefault("_translations", {})
        key = (lang, text)
        if key in cache:
            return cache[key]
        target = {"en": "English", "fr": "French"}.get(lang, lang)
        try:
            provider = self._provider()
            out = "".join(provider.stream(
                f"Translate the user's text into short, natural spoken {target}. Keep names, numbers and "
                "quoted text as they are. Reply with the translation only.",
                [{"role": "user", "content": text}], None)).strip()
        except Exception as exc:  # noqa: BLE001 - never block an action for a translation
            log.warning("Translation failed: %r", exc)
            return text
        if out:
            if len(cache) > 300:
                cache.clear()
            cache[key] = out
        return out or text

    def describe(self) -> str:
        return f"J'utilise {self.label}, avec le modèle {self.model}."

    def reset(self) -> None:
        self.history.clear()

    # -- conversation --------------------------------------------------------------------
    def _system_prompt(self, with_tools: bool) -> str:
        now = datetime.now()
        prompt = self.ai["system_prompt"] + SPEECH_PROMPT + f"\n\nDate et heure locales : {now:%A %d %B %Y, %H:%M}."
        window = _active_window_title()
        if window:
            prompt += f"\nFenêtre active de l'utilisateur : « {window} »."
        return prompt + (TOOLS_PROMPT if with_tools else "")

    def ask(self, user_text: str, tools: list[dict] | None = None) -> Iterator[str]:
        """Yield the answer piece by piece. Raises BrainError on failure."""
        self.last_tool_calls = []
        user_text = (user_text or "").strip()
        if not user_text:
            raise BrainError("empty", "I did not catch anything. Please say or type something.")
        provider = self._provider()
        messages = self.history + [{"role": "user", "content": user_text}]
        parts: list[str] = []
        started = time.perf_counter()
        first_token_at = None
        for attempt in range(2):
            try:
                for text in provider.stream(self._system_prompt(bool(tools)), messages, tools):
                    if first_token_at is None:
                        first_token_at = time.perf_counter() - started
                    parts.append(text)
                    yield text
                break
            except BrainError as err:
                # The model sometimes writes malformed action arguments: one silent retry fixes it.
                malformed = any(k in err.message.lower() for k in ("parse tool call", "tool_use_failed", "failed to call a function"))
                if malformed and attempt == 0 and not parts:
                    log.warning("%s sent a malformed action, retrying once", self.label)
                    continue
                log.error("%s request failed [%s]: %s", self.label, err.kind, err.message)
                if parts and not err.message.startswith("(answer interrupted)"):
                    err.message = "(answer interrupted) " + err.message
                raise
        answer = "".join(parts).strip()
        self.last_tool_calls = list(provider.tool_calls)
        total = time.perf_counter() - started
        log.info("%s answer in %.2fs (first token %.2fs), model=%s, stop=%s, tools=%s", self.label, total,
                 first_token_at or total, provider.served_model or provider.model, provider.stop_reason,
                 [c.name for c in self.last_tool_calls])
        if not answer and not self.last_tool_calls:
            raise BrainError("empty_answer", f"{self.label} returned an empty answer. Try rephrasing.")

        # Plain-text history only (works with every provider), kept short to stay fast and cheap.
        summary = answer or "C'est fait."
        if len(summary) > 500:
            summary = summary[:500] + "…"
        self.history = messages + [{"role": "assistant", "content": summary}]
        max_messages = int(self.ai["history_turns"]) * 2
        self.history = self.history[-max_messages:] if max_messages else []
