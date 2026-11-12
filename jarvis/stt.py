"""Speech-to-text and wake word, fully offline with a small Vosk French model (~70 MB on disk).

One continuous recognizer does both jobs: it listens for the wake word ("jarvis") and
returns what was said after it, e.g. "Jarvis, quelle heure est-il" -> "quelle heure est-il".
The microphone is ignored while Jarvis speaks, so it never answers itself.
"""
from __future__ import annotations

import array
import json
import queue
import re
import threading
import time
from collections.abc import Callable

from jarvis.logger import get_logger
from jarvis.paths import ROOT

log = get_logger(__name__)

SAMPLE_RATE = 16000
BLOCK_FRAMES = 1600  # 100 ms per block


class MicError(Exception):
    """Microphone or speech model problem, with a user-facing message."""


def model_dir(cfg: dict):
    from pathlib import Path

    path = Path(cfg["listening"]["model_path"])
    return path if path.is_absolute() else ROOT / path


_model_cache: dict = {}
_model_lock = threading.Lock()


def load_model(cfg: dict):
    path = model_dir(cfg)
    with _model_lock:
        if str(path) in _model_cache:
            return _model_cache[str(path)]
        if not (path / "am" / "final.mdl").exists():
            raise MicError(f"Speech model not found in '{path}'. Run install.bat to download it.")
        try:
            import vosk

            vosk.SetLogLevel(-1)
            started = time.perf_counter()
            model = vosk.Model(str(path))
            log.info("Vosk model loaded in %.1fs", time.perf_counter() - started)
        except Exception as exc:  # noqa: BLE001
            raise MicError(f"Speech model could not be loaded ({exc}). Run install.bat to download it again.") from exc
        _model_cache[str(path)] = model
        return model


def _resolve_device(device):
    """Accept null, a device number, or part of a device name from config.json."""
    if device is None or isinstance(device, int):
        return device
    import sounddevice as sd

    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0 and device.lower() in info["name"].lower():
            return index
    raise MicError(f"No microphone named '{device}' was found. Fix listening.input_device in config.json (null = default).")


def _mic_error_message(exc: Exception) -> str:
    text = str(exc)
    if "Invalid device" in text or "-9996" in text or "No Default Input Device" in text or "-9998" in text:
        return "No microphone found. Plug in a microphone or enable it in Windows sound settings."
    if "-9985" in text or "unavailable" in text.lower():
        return "The microphone is busy or blocked. Close other apps using it and check Settings > Privacy > Microphone (allow desktop apps)."
    return f"The microphone could not be opened ({text}). Check Settings > Privacy > Microphone."


class Listener:
    def __init__(self, cfg: dict):
        self.cfg = cfg["listening"]
        self.full_cfg = cfg
        self.wake_words = set(self.cfg["wake_words"])
        self.wake_alternatives = set(self.cfg["wake_alternatives"])
        self._audio: queue.Queue[bytes] = queue.Queue(maxsize=600)
        self._stream = None
        self._muted = threading.Event()
        self._model = None
        self._rec = None
        self.level = 0.0          # current microphone level (0..1), for the HUD later
        self.transcriber = None   # optional cloud speech-to-text (cloud_stt.GroqWhisper)
        self.status_error = ""

    # -- microphone ----------------------------------------------------------------------
    def open(self, use_microphone: bool = True) -> None:
        """Load the model and start the microphone. Raises MicError with a clear message.
        use_microphone=False only loads the model (audio is injected by the self-test)."""
        self._model = load_model(self.full_cfg)
        import vosk

        self._rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
        self._wake_rec = None
        if self.cfg.get("wake_grammar", True):
            # A recognizer that only knows "jarvis": much more sensitive to the wake word than the
            # general model (87% vs 50% in tests), but with false alarms, so Whisper confirms them.
            words = [w for w in self.wake_words if " " not in w] or ["jarvis"]
            self._wake_rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE, json.dumps(words + ["[unk]"]))
        nbest = int(self.cfg.get("wake_nbest", 0))
        if nbest > 1:
            # Keep the N best guesses: "Jarvis" is often among them even when the top guess is wrong.
            self._rec.SetMaxAlternatives(nbest)
        self._injected = not use_microphone
        if self._injected:
            return
        try:
            import sounddevice as sd

            device = _resolve_device(self.cfg.get("input_device"))
            self._stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE, blocksize=BLOCK_FRAMES, dtype="int16",
                channels=1, device=device, callback=self._on_audio,
            )
            self._stream.start()
        except MicError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.error("Microphone open failed: %r", exc)
            raise MicError(_mic_error_message(exc)) from exc
        log.info("Microphone opened (device=%s)", self.cfg.get("input_device"))

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:  # noqa: BLE001
                pass
            self._stream = None

    def _on_audio(self, indata, frames, time_info, status) -> None:  # PortAudio thread
        if status:
            self.status_error = str(status)
        data = bytes(indata)
        if self._muted.is_set():
            self.level = 0.0
            return
        # Cheap level estimate on a few samples (no numpy needed).
        peak = 0
        for i in range(0, len(data) - 1, 64):
            value = abs(int.from_bytes(data[i:i + 2], "little", signed=True))
            peak = max(peak, value)
        self.level = min(1.0, peak / 12000)
        try:
            self._audio.put_nowait(data)
        except queue.Full:
            pass

    def mute(self) -> None:
        """Ignore the microphone (while Jarvis is speaking)."""
        self._muted.set()

    def unmute(self) -> None:
        self._drain()
        if self._rec is not None:
            self._rec.Reset()
        if getattr(self, "_wake_rec", None) is not None:
            self._wake_rec.Reset()
        self._muted.clear()

    def _drain(self) -> None:
        try:
            while True:
                self._audio.get_nowait()
        except queue.Empty:
            pass

    def is_alive(self) -> bool:
        if getattr(self, "_injected", False):
            return True
        return self._stream is not None and self._stream.active

    # -- recognition ---------------------------------------------------------------------
    # What the offline model often hears instead of "Jarvis" (seen in real use). Only used
    # to *trigger* a cloud check: Whisper must then confirm that "Jarvis" was really said.
    SOUNDALIKES = {"jarvi", "javis", "garvis", "charvis", "gervais", "j'avais", "gary", "garry", "jarry", "jarre",
                   "thierry", "service", "davis", "travis", "harvey", "jar", "jardin", "jarvisse", "charvi",
                   "java", "jean", "louis", "larry", "jarvisme", "j avais", "avis"}

    def _split_wake(self, text: str) -> tuple[bool, str]:
        """Return (wake word found, words after the last wake word)."""
        words = text.split()
        for index in range(len(words) - 1, -1, -1):
            if words[index] in self.wake_words:
                return True, " ".join(words[index + 1:])
        # Sound-alikes (e.g. "j'avais") only count as the very first word, to limit false wakes.
        if words and words[0] in self.wake_alternatives:
            return True, " ".join(words[1:])
        return False, ""

    def _final(self) -> str:
        """Final result of the recognizer (best guess); keeps the other guesses in _last_alts."""
        res = json.loads(self._rec.Result())
        if "alternatives" in res:
            self._last_alts = [a.get("text", "").strip() for a in res["alternatives"]]
            return self._last_alts[0] if self._last_alts else ""
        text = res.get("text", "").strip()
        self._last_alts = [text]
        return text

    def _cloud_check_allowed(self, per_minute: int = 12) -> bool:
        """Limit the Whisper checks of *possible* wake words (protects the free Groq quota
        when people talk nearby or the TV is on)."""
        now = time.monotonic()
        stamps = [t for t in getattr(self, "_cloud_checks", []) if now - t < 60]
        if len(stamps) >= per_minute:
            self._cloud_checks = stamps
            return False
        stamps.append(now)
        self._cloud_checks = stamps
        return True

    def _maybe_wake(self, text: str) -> bool:
        """The sentence starts with something that could be a badly heard "Jarvis"
        (in the best guess or in one of the alternative guesses)."""
        from jarvis.textnorm import simple

        for candidate in [text] + list(getattr(self, "_last_alts", [])):
            words = simple(candidate).split()[:2]
            if any(w in self.SOUNDALIKES or w in self.wake_words for w in words):
                return True
        return False

    @staticmethod
    def _split_wake_text(text: str) -> tuple[bool, str]:
        """Find "Jarvis" near the start of a Whisper transcript; return (found, the rest)."""
        m = re.search(r"\b(?:jarvis|jarvi|javis|jarviss?e)\b[\s,.!?:;-]*", text, flags=re.IGNORECASE)
        if m and len(text[:m.start()].split()) <= 3:
            return True, text[m.end():].strip(" ,.!?;:-")
        # Whisper puts a comma after the name it was called by, even when it misspells it:
        # "Jardis, ouvre..." / "Jarrez un avis, rappelle-moi..." / "Garvis, quelle heure..."
        head, sep, rest = text.partition(",")
        if sep and len(head.split()) <= 3:
            from jarvis.textnorm import simple

            if any(re.match(r"^(?:j|g|ch)[ae]r\w*$|^ja\w*vi\w*$", w) for w in simple(head).split()):
                return True, rest.strip(" ,.!?;:-")
        # No comma: a Jarvis-like word among the first four words ("J'ai un Jardis ouvre WhatsApp").
        words = text.split()
        for i, word in enumerate(words[:4]):
            w = re.sub(r"[^a-zàâäéèêëïîôöùûüç']", "", word.lower())
            first_word_like = i == 0 and re.match(r"^(?:j|g|ch)[ae]rr?[a-zé]*$", w) and w not in ("jardin", "jardins", "garde", "gare", "garder", "char", "cher", "chère", "chez")
            if first_word_like or re.match(r"^(?:jarvis|jardis|jarvi|javis|garvis|gervais|jarviss?e|jarrez)$", w):
                return True, " ".join(words[i + 1:]).strip(" ,.!?;:-")
        return False, text.strip(" ,.!?;:-")

    @staticmethod
    def _is_wake_only(spoken: str, vosk_heard_only_wake: bool) -> bool:
        """A very short Whisper result that is just a misspelled "Jarvis" ("J'avis.", "Jarder !")."""
        from jarvis.textnorm import simple

        words = simple(spoken).split()
        if not words or len(words) > 3:
            return False
        if vosk_heard_only_wake:
            return True
        return bool(re.match(r"^(?:j|g|ch)[ae]r\w*$|^ja?vi\w*$", words[0])) and len(words) <= 2

    def listen(
        self,
        require_wake: bool = True,
        timeout: float | None = None,
        on_wake: Callable[[bool], None] | None = None,
        on_partial: Callable[[str], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> str | None:
        """Block until a command is heard.

        require_wake=True: wait (forever) for the wake word, then return what follows it
        (in the same sentence or in the next one, within command_timeout_seconds).
        require_wake=False: return the next sentence, or None after `timeout` seconds of silence.
        With a cloud transcriber, the returned text comes from Whisper (much more accurate).
        """
        if self._rec is None:
            raise MicError("The microphone is not open.")
        woke = not require_wake
        deadline = time.monotonic() + timeout if timeout else None
        heard_speech = False
        last_partial = ""
        command_timeout = float(self.cfg["command_timeout_seconds"])
        chunks: list[bytes] = []          # audio of the current sentence
        speech_start: int | None = None   # chunk index where speech started

        while True:
            if should_stop and should_stop():
                return None
            if not self.is_alive():
                raise MicError("The microphone stopped working (unplugged or disabled).")
            try:
                data = self._audio.get(timeout=0.2)
            except queue.Empty:
                data = None
            now = time.monotonic()
            if deadline and now > deadline and not heard_speech:
                return None
            if data is None:
                continue
            chunks.append(data)
            if speech_start is None and len(chunks) > 150:  # keep at most 15 s of leading silence
                del chunks[:-10]
            if not woke and self._wake_rec is not None:
                self._wake_rec.AcceptWaveform(data)

            if self._rec.AcceptWaveform(data):
                text = self._final()
                start = max(0, (speech_start or 0) - 5)  # 0.5 s before the speech started
                audio = b"".join(chunks[start:])
                chunks, speech_start, heard_speech = [], None, False
                if not text:
                    continue
                peak = max((abs(s) for s in array.array("h", audio[: len(audio) - len(audio) % 2])[::8]), default=0)
                log.info("Heard: %r (peak level %.0f%%)", text, peak / 327.68)
                vosk_wake, vosk_after = self._split_wake(text)
                cloud = self.transcriber if (self.transcriber is not None and self.transcriber.available()) else None
                grammar_hit = False
                if self._wake_rec is not None:
                    heard = json.loads(self._wake_rec.FinalResult()).get("text", "")
                    grammar_hit = any(w in self.wake_words for w in heard.split()[:2])

                if not woke and not vosk_wake:
                    maybe = self._maybe_wake(text) or grammar_hit
                    if not (cloud and maybe and self._cloud_check_allowed()):
                        continue  # no wake word: ignore this sentence
                # "Jarvis" alone is the one thing the offline model hears reliably; Whisper tends to
                # invent a sentence for it ("J'ai une petite question"), so trust Vosk here.
                if cloud is not None and not (vosk_wake and not vosk_after):
                    spoken = cloud.transcribe(audio)
                    if spoken is not None:  # the cloud answered (None = failure -> offline text below)
                        found, after = self._split_wake_text(spoken)
                        if not found and self._is_wake_only(spoken, vosk_wake and not vosk_after):
                            found, after = True, ""  # "J'avis.", "Jardim.", "Jarrez." = just "Jarvis"
                        if vosk_wake and not found:
                            # Vosk heard "Jarvis" but Whisper garbled it ("J'ai un petit peu de service,
                            # ouvre..."): drop what comes before the first comma.
                            head, sep, rest = after.partition(",")
                            if sep and len(head.split()) <= 6 and rest.strip():
                                after = rest.strip(" ,.!?;:-")
                        if not woke and not found and not vosk_wake:
                            log.info("False wake ignored (Whisper heard %r)", spoken)
                            continue
                        if not after and (found or vosk_wake):
                            woke, deadline = True, now + command_timeout
                            if on_wake:
                                on_wake(False)
                            continue
                        if not after:
                            continue  # silence or noise
                        if on_wake and not woke:
                            on_wake(True)
                        return after
                # Offline text (no cloud transcriber, or it failed).
                if vosk_wake and not vosk_after:
                    # Only "Jarvis" was said: beep (early=False) and wait for the next sentence.
                    woke = True
                    deadline = now + command_timeout
                    if on_wake:
                        on_wake(False)
                    continue
                if woke:
                    return vosk_after if vosk_wake else text
                if vosk_wake:
                    if on_wake:
                        on_wake(True)
                    return vosk_after
            else:
                partial = json.loads(self._rec.PartialResult()).get("partial", "").strip()
                if partial:
                    if speech_start is None:
                        speech_start = len(chunks) - 1
                    heard_speech = True
                    if on_partial and partial != last_partial:
                        on_partial(partial)
                    last_partial = partial
                    if not woke and self._split_wake(partial)[0]:
                        # Early feedback: react to "Jarvis" before the sentence ends.
                        woke = True
                        deadline = None
                        if on_wake:
                            on_wake(True)

    def monitor_barge_in(self, stop: threading.Event, is_echo: Callable[[list[str]], bool],
                         on_trigger: Callable[[], None], max_after_trigger: float = 9.0) -> str | None:
        """Listen while Jarvis speaks. If the user starts talking (not Jarvis's own echo), call
        on_trigger() (which stops the voice) and return what the user says; None otherwise."""
        if self._rec is None:
            return None
        self.unmute()
        triggered = False
        trigger_time = 0.0
        chunks: list[bytes] = []
        speech_start: int | None = None
        final_text = ""
        try:
            while True:
                if not triggered and stop.is_set():
                    return None
                if triggered and time.monotonic() - trigger_time > max_after_trigger:
                    break
                try:
                    data = self._audio.get(timeout=0.1)
                except queue.Empty:
                    continue
                chunks.append(data)
                if speech_start is None and len(chunks) > 150:
                    del chunks[:-10]
                if self._rec.AcceptWaveform(data):
                    text = self._final()
                    if triggered:
                        final_text = text
                        break
                    if text and not is_echo(text.split()):
                        triggered, trigger_time, final_text = True, time.monotonic(), text
                        on_trigger()
                        break
                    chunks, speech_start = [], None
                else:
                    partial = json.loads(self._rec.PartialResult()).get("partial", "").strip()
                    if partial and speech_start is None:
                        speech_start = len(chunks) - 1
                    if partial and not triggered and not is_echo(partial.split()):
                        triggered, trigger_time = True, time.monotonic()
                        log.info("Barge-in: %r", partial)
                        on_trigger()
        finally:
            self.mute()
        if not triggered:
            return None
        audio = b"".join(chunks[max(0, (speech_start or 0) - 5):])
        cloud = self.transcriber if (self.transcriber is not None and self.transcriber.available()) else None
        if cloud is not None:
            spoken = cloud.transcribe(audio)
            if spoken:
                final_text = spoken
        found, after = self._split_wake_text(final_text)
        return (after if found else final_text).strip() or None

    def feed_pcm_for_test(self, pcm: bytes) -> None:
        """Inject 16 kHz mono PCM as if it came from the microphone (self-test)."""
        for i in range(0, len(pcm), BLOCK_FRAMES * 2):
            self._audio.put(pcm[i:i + BLOCK_FRAMES * 2])


def record_level(seconds: float = 2.0, device=None) -> tuple[float, int]:
    """Record a moment of sound; return (peak level 0..1, number of blocks). Raises MicError."""
    import sounddevice as sd

    peak = 0
    blocks = 0
    try:
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=BLOCK_FRAMES, dtype="int16",
                               channels=1, device=_resolve_device(device)) as stream:
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                data, _overflow = stream.read(BLOCK_FRAMES)
                data = bytes(data)
                blocks += 1
                for i in range(0, len(data) - 1, 8):
                    peak = max(peak, abs(int.from_bytes(data[i:i + 2], "little", signed=True)))
    except MicError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise MicError(_mic_error_message(exc)) from exc
    return min(1.0, peak / 32768), blocks
