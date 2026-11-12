"""Claude (Anthropic SDK): streaming answers, optional tool calls, clear error messages."""
from __future__ import annotations

from collections.abc import Iterator

from jarvis.logger import get_logger
from jarvis.providers.base import BrainError, ToolCall

log = get_logger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def friendly_error(exc: Exception) -> BrainError:
    """Map Anthropic SDK exceptions to clear messages (most specific first)."""
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return BrainError("auth", "The Claude API key was rejected (invalid or revoked). Run `start.bat --setup-key claude` to enter a new key.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return BrainError("permission", "This Claude API key is not allowed to use this model or feature.")
    if isinstance(exc, anthropic.NotFoundError):
        return BrainError("not_found", "The Claude model in config.json does not exist or is not available to your account.")
    if isinstance(exc, anthropic.RateLimitError):
        return BrainError("rate_limit", "Claude: too many requests or no credit left. Wait a moment, or check billing on console.anthropic.com.")
    if isinstance(exc, anthropic.BadRequestError):
        text = str(exc).lower()
        if "credit" in text or "billing" in text:
            return BrainError("billing", "Your Anthropic account has no credit left. Add credit on console.anthropic.com > Billing.")
        return BrainError("bad_request", f"The request was refused by the Claude API: {getattr(exc, 'message', exc)}")
    if isinstance(exc, anthropic.APITimeoutError):
        return BrainError("timeout", "Claude did not answer in time. The connection may be slow; try again.")
    if isinstance(exc, anthropic.APIConnectionError):
        return BrainError("connection", "Cannot reach the Claude API. Check your internet connection.")
    if isinstance(exc, anthropic.InternalServerError) or (
        isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500
    ):
        return BrainError("server", "The Claude service is temporarily overloaded or down. Try again in a moment.")
    if isinstance(exc, anthropic.APIStatusError):
        return BrainError("api", f"Claude API error {exc.status_code}: {getattr(exc, 'message', exc)}")
    return BrainError("unknown", f"Unexpected error: {exc.__class__.__name__}: {exc}")


class ClaudeProvider:
    name = "claude"

    def __init__(self, ai_cfg: dict, api_key: str):
        import anthropic

        self.ai = ai_cfg
        self.cfg = ai_cfg["claude"]
        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=anthropic.Timeout(float(ai_cfg["timeout_seconds"]), connect=5.0),
            max_retries=int(ai_cfg["max_retries"]),
        )
        self.tool_calls: list[ToolCall] = []
        self.stop_reason: str | None = None
        self.served_model = ""

    @property
    def model(self) -> str:
        return self.cfg["model"]

    def verify(self) -> str:
        """Check the key and the model with free calls. Returns the model id."""
        try:
            self.client.models.list(limit=1)
            return self.client.models.retrieve(self.model).id
        except Exception as exc:  # noqa: BLE001
            raise friendly_error(exc) from exc

    def _open_stream(self, system: str, messages: list[dict], tools: list[dict] | None):
        params = {
            "model": self.model,
            "max_tokens": int(self.ai["max_tokens"]),
            "system": system,
            "messages": messages,
            "output_config": {"effort": self.cfg["effort"]},
        }
        if tools:
            # Streaming request with client tools: stream tool inputs as generated; we validate them ourselves.
            params["tools"] = [{"name": t["name"], "description": t["description"],
                                "input_schema": t["parameters"], "eager_input_streaming": True} for t in tools]
        if self.cfg["refusal_fallback"]:
            # If the main model declines, the API re-runs the request on a fallback model.
            return self.client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks="default", **params)
        return self.client.messages.stream(**params)

    def stream(self, system: str, messages: list[dict], tools: list[dict] | None = None) -> Iterator[str]:
        self.tool_calls = []
        self.stop_reason = None
        try:
            with self._open_stream(system, messages, tools) as stream:
                for text in stream.text_stream:
                    yield text
                final = stream.get_final_message()
        except ValueError as exc:
            # A tool input arrived as JSON the SDK could not parse at all.
            log.error("Unparsable tool input from Claude: %r", exc)
            raise BrainError("bad_tool", "I did not understand which action to run. Please rephrase.") from exc
        except BrainError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise friendly_error(exc) from exc
        self.stop_reason = getattr(final, "stop_reason", None)
        self.served_model = getattr(final, "model", "")
        if self.stop_reason is None:
            raise BrainError("connection", "(answer interrupted) The connection to Claude was lost. Check your internet and try again.")
        if self.stop_reason == "refusal":
            raise BrainError("refusal", "Claude declined to answer this request.")
        if self.stop_reason == "max_tokens":
            return  # never run a tool call whose input may be truncated
        for block in final.content:
            if getattr(block, "type", "") == "tool_use":
                self.tool_calls.append(ToolCall(block.name, block.input))
