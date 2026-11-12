"""Groq, Gemini and OpenAI through their OpenAI-compatible chat API (one SDK for the three)."""
from __future__ import annotations

import json
from collections.abc import Iterator

from jarvis.logger import get_logger
from jarvis.providers import PROVIDERS
from jarvis.providers.base import BrainError, ToolCall, strip_key

log = get_logger(__name__)


def friendly_error(exc: Exception, label: str, name: str) -> BrainError:
    import openai

    if isinstance(exc, openai.AuthenticationError):
        return BrainError("auth", f"The {label} API key was rejected. Run `start.bat --setup-key {name}` to enter a new key.")
    if isinstance(exc, openai.PermissionDeniedError):
        return BrainError("permission", f"This {label} API key is not allowed to use this model (or not in your region).")
    if isinstance(exc, openai.NotFoundError):
        return BrainError("not_found", f"The {label} model in config.json does not exist. Run test.bat to see the available models.")
    if isinstance(exc, openai.RateLimitError):
        return BrainError("rate_limit", f"{label}: too many requests or quota exhausted. Wait a moment or check your plan.")
    if isinstance(exc, openai.BadRequestError):
        return BrainError("bad_request", f"The request was refused by {label}: {getattr(exc, 'message', exc)}")
    if isinstance(exc, openai.APITimeoutError):
        return BrainError("timeout", f"{label} did not answer in time. Try again.")
    if isinstance(exc, openai.APIConnectionError):
        return BrainError("connection", f"Cannot reach {label}. Check your internet connection.")
    if isinstance(exc, openai.InternalServerError) or (isinstance(exc, openai.APIStatusError) and exc.status_code >= 500):
        return BrainError("server", f"The {label} service is temporarily overloaded or down. Try again in a moment.")
    if isinstance(exc, openai.APIStatusError):
        return BrainError("api", f"{label} API error {exc.status_code}: {getattr(exc, 'message', exc)}")
    return BrainError("unknown", f"Unexpected error: {exc.__class__.__name__}: {exc}")


class OpenAICompatProvider:
    def __init__(self, name: str, ai_cfg: dict, api_key: str):
        import openai

        self.name = name
        self.label = PROVIDERS[name].label
        self.ai = ai_cfg
        self.cfg = ai_cfg[name]
        self.client = openai.OpenAI(
            api_key=api_key, base_url=self.cfg["base_url"],
            timeout=float(ai_cfg["timeout_seconds"]), max_retries=int(ai_cfg["max_retries"]),
        )
        self.tool_calls: list[ToolCall] = []
        self.stop_reason: str | None = None
        self.served_model = ""
        self._token_param = "max_tokens"

    @property
    def model(self) -> str:
        return self.cfg["model"]

    def available_models(self) -> list[str]:
        try:
            return sorted(m.id for m in self.client.models.list())
        except Exception as exc:  # noqa: BLE001
            raise friendly_error(exc, self.label, self.name) from exc

    def verify(self) -> str:
        models = self.available_models()
        short = {m.removeprefix("models/") for m in models}
        if self.model not in short and models:
            hint = ", ".join(m for m in sorted(short) if not any(x in m for x in ("embed", "whisper", "tts", "image", "audio")))[:300]
            raise BrainError("not_found", f"Model '{self.model}' is not available on {self.label}. Available: {hint}")
        return self.model

    def _tools(self, tools: list[dict]) -> list[dict]:
        converted = []
        for t in tools:
            params = t["parameters"]
            if self.name == "gemini":  # Gemini's function schema rejects additionalProperties
                params = strip_key(params, "additionalProperties")
            converted.append({"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": params}})
        return converted

    def _create(self, system: str, messages: list[dict], tools: list[dict] | None, model: str | None = None):
        kwargs = {
            "model": model or self.model,
            "messages": [{"role": "system", "content": system}] + messages,
            "stream": True,
            self._token_param: int(self.ai["max_tokens"]),
        }
        if tools:
            kwargs["tools"] = self._tools(tools)
        if "qwen" in kwargs["model"]:
            kwargs["reasoning_effort"] = "none"  # Qwen: no hidden "thinking" (fast, no stray text)
        elif self.cfg.get("reasoning_effort"):
            kwargs["reasoning_effort"] = self.cfg["reasoning_effort"]  # fewer hidden tokens = faster, cheaper
        extra = self.cfg.get("extra_body")
        if isinstance(extra, dict) and extra:
            kwargs["extra_body"] = extra
        # No silent SDK wait on "429 too many requests": the fallback model answers right away instead.
        client = self.client.with_options(max_retries=0) if self._fallbacks() else self.client
        return client.chat.completions.create(**kwargs)

    def _fallbacks(self) -> list[str]:
        models = self.cfg.get("fallback_models") or ([self.cfg["fallback_model"]] if self.cfg.get("fallback_model") else [])
        return [m for m in models if m and m != self.model]

    def _create_any(self, system: str, messages: list[dict], tools: list[dict] | None):
        """Free plans limit tokens per minute *per model*: when one model is busy, the next answers
        at once. If all are busy, wait only when the service asks for a few seconds."""
        import re
        import time

        import openai

        models = [self.model] + self._fallbacks()
        waits: list[tuple[float, str]] = []
        last: Exception | None = None
        for model in models:
            try:
                if model != self.model:
                    log.warning("%s rate limit, using %s for this answer", self.label, model)
                return self._create(system, messages, tools, model=model)
            except openai.RateLimitError as exc:
                last = exc
                m = re.search(r"try again in ([\d.]+)s", str(exc))
                waits.append((float(m.group(1)) if m else 99.0, model))
        wait, model = min(waits) if waits else (99.0, self.model)
        if wait > 8 or last is None:
            raise last if last else RuntimeError("no model")
        log.warning("%s: every model is rate-limited, waiting %.1fs", self.label, wait)
        time.sleep(wait + 0.3)
        return self._create(system, messages, tools, model=model)

    def stream(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> Iterator[str]:
        import openai

        self.tool_calls = []
        self.stop_reason = None
        calls: dict[int, dict] = {}
        try:
            try:
                response = self._create_any(system, messages, tools)
            except openai.BadRequestError as exc:
                # Some newer OpenAI models only accept max_completion_tokens.
                if "max_completion_tokens" in str(exc) and self._token_param == "max_tokens":
                    self._token_param = "max_completion_tokens"
                    response = self._create(system, messages, tools)
                else:
                    raise
            for chunk in response:
                if getattr(chunk, "model", None):
                    self.served_model = chunk.model
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is not None:
                    if delta.content:
                        yield delta.content
                    for tc in delta.tool_calls or []:
                        entry = calls.setdefault(tc.index or 0, {"name": "", "args": ""})
                        if tc.function is not None:
                            if tc.function.name:
                                entry["name"] = tc.function.name
                            if tc.function.arguments:
                                entry["args"] += tc.function.arguments
                if choice.finish_reason:
                    self.stop_reason = choice.finish_reason
        except BrainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise friendly_error(exc, self.label, self.name) from exc
        if self.stop_reason is None:
            raise BrainError("connection", f"(answer interrupted) The connection to {self.label} was lost.")
        if self.stop_reason == "content_filter":
            raise BrainError("refusal", f"{self.label} declined to answer this request.")
        if self.stop_reason == "length":
            return  # never run a possibly truncated tool call
        for entry in calls.values():
            if not entry["name"]:
                continue
            try:
                args = json.loads(entry["args"] or "{}")
            except ValueError:
                log.error("Invalid tool arguments from %s: %r", self.label, entry["args"][:200])
                raise BrainError("bad_tool", "I did not understand which action to run. Please rephrase.") from None
            self.tool_calls.append(ToolCall(entry["name"], args))
