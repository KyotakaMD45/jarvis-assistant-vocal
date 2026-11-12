"""Accurate speech-to-text in the cloud (Groq Whisper), used for the sentence after "Jarvis".

Vosk (offline) keeps listening continuously for the wake word; only the short audio of a
sentence that starts with "Jarvis" (or a sound-alike) is sent to Whisper, which understands
real voices far better. If the cloud is unreachable, Jarvis falls back to the Vosk text.
"""
from __future__ import annotations

import array
import io
import re
import time
import wave

from jarvis.api_key import get_api_key, looks_like_key
from jarvis.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 16000
# Spelling hints: Whisper writes these words correctly when they appear in the prompt.
# Kept to one word on purpose: Whisper copies longer prompts into its output on short or
# unclear audio (it once "heard" a whole example sentence and opened WhatsApp).
PROMPT = "Knull."
# Text Whisper is known to invent on silence or noise.
_HALLUCINATIONS = re.compile(
    r"(sous-titr|amara\.org|merci d'avoir regard|abonnez-vous|merci de votre attention|^\W*merci\.?\W*$|^\W*$)",
    re.IGNORECASE,
)


def _wav_bytes(pcm: bytes) -> bytes:
    """16 kHz mono PCM -> WAV, louder if the microphone level is low (Whisper copes better)."""
    samples = array.array("h", pcm[: len(pcm) - len(pcm) % 2])
    peak = max((abs(s) for s in samples[::4]), default=0)
    if 0 < peak < 16000:
        gain = min(8.0, 16000 / peak)
        samples = array.array("h", (max(-32768, min(32767, int(s * gain))) for s in samples))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


class GroqWhisper:
    def __init__(self, cfg: dict):
        self.ai = cfg["ai"]
        self.model = cfg["listening"]["cloud_model"]
        # Languages the user speaks: with several, Whisper detects which one (no slower, and an
        # English sentence is no longer forced into French words). The first is the fallback.
        self.languages = [str(x).lower()[:2] for x in cfg["listening"].get("languages", ["fr"])] or ["fr"]
        self.last_language = self.languages[0]
        self._client = None
        self._key = ""
        self.last_error = ""

    def available(self) -> bool:
        key, _ = get_api_key("groq")
        return bool(key) and looks_like_key(key, "groq")

    def _get_client(self):
        key, _ = get_api_key("groq")
        if self._client is None or key != self._key:
            from jarvis.jiter_fallback import ensure_jiter

            ensure_jiter()
            import openai

            self._client = openai.OpenAI(api_key=key, base_url=self.ai["groq"]["base_url"], timeout=8.0, max_retries=0)
            self._key = key
        return self._client

    def warm_up(self) -> None:
        try:
            self._get_client()
        except Exception:  # noqa: BLE001
            log.exception("Cloud speech recognition warm-up failed")

    # Short French answers that Whisper's language detection turns into English ("oui" -> "Bye.").
    FRENCH_SHORT = {"oui", "non", "merci", "salut", "ouais", "d'accord", "daccord", "vas-y", "vas y", "ok merci",
                    "oui merci", "non merci", "bonjour", "bonsoir", "voila", "exactement", "bien sur"}

    def transcribe(self, pcm: bytes, wake_hint: bool = True, offline: str = "") -> str | None:
        """Return the text, "" for silence/noise, or None if the cloud failed (use the offline text).

        wake_hint=True gives Whisper the spelling of "Jarvis" (to detect the wake word). It must be
        False for the rest of a conversation: on short or unclear commands Whisper otherwise answers
        with the prompt itself ("regarde à droite" came back as "Jarvis.")."""
        if len(pcm) < SAMPLE_RATE * 2 * 0.3:  # less than 0.3 s of audio
            return ""
        started = time.perf_counter()
        wav = _wav_bytes(pcm)
        prompt = {"prompt": PROMPT} if wake_hint else {}
        try:
            client = self._get_client()
            # Language detection is unreliable on short clips ("oui" came back as "Bye."): when the
            # offline (French) model clearly heard a short French answer, keep French.
            from jarvis.textnorm import simple

            heard = simple(offline or "")
            french_answer = len(pcm) < SAMPLE_RATE * 2 * 2.5 and (
                heard in self.FRENCH_SHORT or heard.split()[:1] in (["oui"], ["non"], ["merci"], ["salut"]))
            if len(self.languages) == 1 or french_answer:
                result = client.audio.transcriptions.create(
                    model=self.model, file=("speech.wav", wav, "audio/wav"), language=self.languages[0],
                    temperature=0, response_format="json", **prompt)
                self.last_language = self.languages[0]
            else:
                result = client.audio.transcriptions.create(
                    model=self.model, file=("speech.wav", wav, "audio/wav"),
                    temperature=0, response_format="verbose_json", **prompt)
                detected = str(getattr(result, "language", "") or "").lower()
                code = {"french": "fr", "english": "en"}.get(detected, detected[:2])
                if code not in self.languages:
                    # Another language detected on a short or noisy clip: use the main language.
                    result = client.audio.transcriptions.create(
                        model=self.model, file=("speech.wav", wav, "audio/wav"), language=self.languages[0],
                        temperature=0, response_format="json", **prompt)
                    code = self.languages[0]
                self.last_language = code
        except Exception as exc:  # noqa: BLE001 - offline, quota, bad key...: fall back to Vosk
            self.last_error = f"{exc.__class__.__name__}: {exc}"
            log.warning("Cloud transcription failed, using the offline text: %s", self.last_error[:200])
            return None
        text = (getattr(result, "text", "") or "").strip()
        if _HALLUCINATIONS.search(text):
            log.info("Cloud transcription ignored (noise): %r", text)
            return ""
        log.info("Whisper heard: %r [%s] (%.2fs, %.1fs of audio)", text, self.last_language,
                 time.perf_counter() - started, len(pcm) / (SAMPLE_RATE * 2))
        return text
