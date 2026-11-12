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
        self.last_alternative: str | None = None  # offline transcript of the last sentence
        self.status_error = ""
        # Background noise: sentences quieter than this (percent of full scale) are ignored when the
        # name was not said (follow-up, yes/no), or below the second value while waiting for the name.
        self.min_level_follow = float(self.cfg.get("min_level_follow", 22))
        self.min_level_wake = float(self.cfg.get("min_level_wake", 12))
        # Voice print: sentences clearly spoken by another voice are ignored (see enroll in voice.py).
        self.voice_threshold = float(self.cfg.get("voice_match_threshold", 0.30))
        self._spk_model = None
        self.voiceprint: list[float] | None = None
        self.collect_voice = False                # enrollment: keep the embedding of each sentence
        self.last_spk: tuple[list[float], int] = ([], 0)
        self.echo_check = None                    # set by the assistant: text -> "is it my own voice?"
        self.last_audio = b""

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
            words = [("null" if w == "knull" else w) for w in self.wake_words if " " not in w] or ["jarvis"]
            self._wake_rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE, json.dumps(words + ["[unk]"]))
        self.load_voice()
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

    # -- voice print -----------------------------------------------------------------------
    VOICEPRINT = ROOT / "voiceprint.json"

    def load_voice(self) -> None:
        """Load the speaker model (models/vosk-model-spk-0.4) and the owner's voice print, if any."""
        import vosk

        path = ROOT / "models" / "vosk-model-spk-0.4"
        if path.exists() and self._spk_model is None:
            try:
                self._spk_model = vosk.SpkModel(str(path))
            except Exception:  # noqa: BLE001
                log.exception("Speaker model failed to load")
        try:
            data = json.loads(self.VOICEPRINT.read_text(encoding="utf-8"))
            self.voiceprint = data.get("vector") or None
        except (OSError, ValueError):
            self.voiceprint = None
        log.info("Voice print: %s", "enrolled" if self.voiceprint else "none (say 'apprends ma voix')")

    def save_voiceprint(self, vectors: list[list[float]]) -> None:
        mean = [sum(c) / len(vectors) for c in zip(*vectors)]
        self.VOICEPRINT.write_text(json.dumps({"vector": mean, "samples": len(vectors)}), encoding="utf-8")
        self.voiceprint = mean

    def forget_voiceprint(self) -> None:
        self.VOICEPRINT.unlink(missing_ok=True)
        self.voiceprint = None

    def embed(self, audio: bytes) -> tuple[list[float], int]:
        if self._spk_model is None or not audio:
            return [], 0
        import vosk

        rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
        rec.SetSpkModel(self._spk_model)
        rec.AcceptWaveform(audio)
        res = json.loads(rec.FinalResult())
        return res.get("spk") or [], int(res.get("spk_frames") or 0)

    @staticmethod
    def similarity(a: list[float], b: list[float]) -> float:
        import math

        na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
        return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0

    def _accept(self, text: str, audio: bytes, peak_percent: float, named: bool) -> bool:
        """Background noise filter: too quiet, or clearly not the owner's voice -> ignore."""
        if self.echo_check is not None and self.echo_check(text):
            log.info("Ignored: Knull's own voice picked up by the microphone: %r", text)
            return False
        floor = self.min_level_wake if named else self.min_level_follow
        if peak_percent < floor:
            log.info("Ignored (too quiet for a command, %.0f%% < %.0f%%): %r", peak_percent, floor, text)
            return False
        if self._spk_model is not None and (self.voiceprint or self.collect_voice):
            vec, frames = self.embed(audio)
            self.last_spk = (vec, frames)
            if self.voiceprint and vec and frames >= 80:  # short words carry too little voice
                sim = self.similarity(self.voiceprint, vec)
                if sim < self.voice_threshold:
                    log.info("Ignored: another voice (similarity %.2f): %r", sim, text)
                    return False
                log.info("Voice check ok (similarity %.2f)", sim)
        return True

    # -- recognition ---------------------------------------------------------------------
    # What the offline model often hears instead of "Jarvis" (seen in real use). Only used
    # to *trigger* a cloud check: Whisper must then confirm that "Jarvis" was really said.
    SOUNDALIKES = {"jarvi", "javis", "garvis", "charvis", "gervais", "j'avais", "gary", "garry", "jarry", "jarre",
                   "thierry", "service", "davis", "travis", "harvey", "jar", "jardin", "jarvisse", "charvi",
                   "java", "jean", "louis", "larry", "jarvisme", "j avais", "avis",
                   # "Apex"
                   "atex", "apec", "apecs", "appex", "apax", "epee", "help", "pex", "apnee", "cnl",
                   # "Knull" (the offline model writes "nul", "null", "cnil", "knoll"...)
                   "nul", "nulle", "nuls", "null", "knull", "knoll", "cnil", "neul", "nole", "klaus"}

    def _split_wake(self, text: str) -> tuple[bool, str]:
        """Return (wake word found, words after the last wake word)."""
        words = text.split()
        if len(words) >= 2 and words[-1] in self.wake_words and words[0] not in self.wake_words:
            return True, " ".join(words[:-1])  # "au revoir jarvis" -> "au revoir"
        for index in range(len(words) - 1, -1, -1):
            if words[index] in self.wake_words:
                return True, " ".join(words[index + 1:])
        # Sound-alikes (e.g. "j'avais") only count as the very first word, to limit false wakes.
        if words and words[0] in self.wake_alternatives:
            return True, " ".join(words[1:])
        return False, ""

    @staticmethod
    def _glue(text: str) -> str:
        """Vosk sometimes spells the name "a p ex": glue it back before the wake word checks."""
        return re.sub(r"\ba p ex\b", "apex", text)

    def _final(self) -> str:
        """Final result of the recognizer (best guess); keeps the other guesses in _last_alts."""
        res = json.loads(self._rec.Result())
        for alt in res.get("alternatives", []):
            alt["text"] = self._glue(alt.get("text", ""))
        if "text" in res:
            res["text"] = self._glue(res["text"])
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
        text = re.sub(r"\b[Aa]\.? ?[Pp]\.? ?[Ee]\.? ?[Xx]\b\.?", "Apex", text)  # "A.P.E.X." / "a p ex"
        # "Knull" (and how Whisper may spell it) only counts at the very start of the sentence, maybe
        # after "hey/ok/dis" ("c'est nul" must not wake it up), or at the very end after a comma.
        greeting = r"^\s*(?:(?:hey|h[ée]|eh|ok|okay|dis|yo|salut|bonjour)[\s,]+)?"
        k = re.match(greeting + r"(?:k[- ]?nu+ll?|knoll|k[- ]?noll)\b[\s,.!?:;-]*", text, flags=re.IGNORECASE) \
            or re.match(greeting + r"(?:nu+ll?e?|noll|neul)\s*[,.!?:;]+\s*", text, flags=re.IGNORECASE)  # "Nul, …" not "Nul n'est…"
        if k:
            return True, text[k.end():].strip(" ,.!?;:-")
        k = re.search(r",\s*(?:k[- ]?nu+ll?|knoll)\s*[.!?]*\s*$", text, flags=re.IGNORECASE)
        if k and text[:k.start()].strip(" ,.!?;:-"):
            return True, text[:k.start()].strip(" ,.!?;:-")
        m = re.search(r"\b(?:jarvis|jarvi|javis|jarviss?e|apex|appex|apecs?)\b[\s,.!?:;-]*", text, flags=re.IGNORECASE)
        if m and not text[m.end():].strip(" ,.!?;:-") and text[:m.start()].strip(" ,.!?;:-"):
            # Name at the end: "Au revoir Jarvis." / "Ouvre WhatsApp, Jarvis."
            return True, text[:m.start()].strip(" ,.!?;:-")
        if m and len(text[:m.start()].split()) <= 3:
            return True, text[m.end():].strip(" ,.!?;:-")
        # Whisper puts a comma after the name it was called by, even when it misspells it:
        # "Jardis, ouvre..." / "Jarrez un avis, rappelle-moi..." / "Garvis, quelle heure..."
        head, sep, rest = text.partition(",")
        if sep and len(head.split()) <= 3:
            from jarvis.textnorm import simple

            if any(re.match(r"^(?:j|g|ch)[ae]r\w*$|^ja\w*vi\w*$|^h?a+p+[eiy]+(?:x|ks|cs|c|k)s?$", w) for w in simple(head).split()):
                return True, rest.strip(" ,.!?;:-")
        # No comma: a Jarvis-like word among the first four words ("J'ai un Jardis ouvre WhatsApp").
        words = text.split()
        for i, word in enumerate(words[:4]):
            w = re.sub(r"[^a-zàâäéèêëïîôöùûüç']", "", word.lower())
            first_word_like = i == 0 and re.match(r"^(?:j|g|ch)[ae]rr?[a-zé]*$", w) and w not in ("jardin", "jardins", "garde", "gare", "garder", "char", "cher", "chère", "chez")
            if first_word_like or re.match(r"^(?:jarvis|jardis|jarvi|javis|garvis|gervais|jarviss?e|jarrez|apex|appex|apecs?|apax)$", w):
                return True, " ".join(words[i + 1:]).strip(" ,.!?;:-")
        return False, text.strip(" ,.!?;:-")

    # How the offline model writes "Knull" at the start of a sentence.
    KNULL_LIKE = {"nul", "nulle", "nuls", "null", "knull", "knoll", "cnil", "cnl", "neul", "nole", "klaus", "pneu", "pneus"}

    @classmethod
    def _dropped_name(cls, vosk_text: str, spoken: str, grammar: str) -> tuple[bool, str]:
        """Whisper often leaves out a name it does not know ("Knull, ouvre Chrome" -> "ouvre Chrome").
        If the offline model heard a Knull-like word first and Whisper's text is the rest of what it
        heard, the name was there. ("Nul n'est parfait": Whisper keeps "Nul", so it does not count.)"""
        import difflib

        from jarvis.textnorm import simple

        vw, sw = simple(vosk_text).split(), simple(spoken).split()
        grammar_null = "null" in grammar.split()[:1]
        if not vw or not (vw[0] in cls.KNULL_LIKE or grammar_null):
            return False, ""
        if len(vw) == 1:
            return (grammar_null and len(sw) <= 1), ""  # just "Knull"
        if not sw or sw[0] == vw[0] or sw[0] in cls.KNULL_LIKE:
            return False, ""
        ratio = difflib.SequenceMatcher(None, " ".join(vw[1:]), " ".join(sw)).ratio()
        return (True, spoken.strip(" ,.!?;:-")) if ratio >= 0.55 else (False, "")

    @staticmethod
    def _only_names(text: str) -> bool:
        """The text is just the name, possibly repeated: "Jarvis. Jarvis." / "Jardis Jardis"."""
        from jarvis.textnorm import simple

        words = simple(text).split()
        return bool(words) and len(words) <= 3 and all(
            re.match(r"^(?:jarvis|jardis|jarvi|javis|garvis|jarviss?e|jarrez|(?:j|g|ch)[ae]rr?[dv]is|apex|appex|apecs?|apax|knull|null|nul|knoll)$", w) for w in words)

    @staticmethod
    def _is_wake_only(spoken: str, vosk_heard_only_wake: bool) -> bool:
        """A very short Whisper result that is just a misspelled "Jarvis" ("J'avis.", "Jarder !")."""
        from jarvis.textnorm import simple

        words = simple(spoken).split()
        if not words or len(words) > 3:
            return False
        if vosk_heard_only_wake:
            return True
        return bool(re.match(r"^(?:j|g|ch)[ae]r\w*$|^ja?vi\w*$|^h?a+p+[eiy]+(?:x|ks|cs|c|k)s?$|^k?nu+ll?e?s?$|^knoll$",
                             words[0])) and len(words) <= 2

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
                self.last_audio = audio
                if not self._accept(text, audio, peak / 327.68, named=require_wake):
                    continue
                vosk_wake, vosk_after = self._split_wake(text)
                cloud = self.transcriber if (self.transcriber is not None and self.transcriber.available()) else None
                grammar_hit = False
                heard = ""
                if self._wake_rec is not None:
                    heard = json.loads(self._wake_rec.FinalResult()).get("text", "")
                    grammar_hit = any(w in self.wake_words or w == "null" for w in heard.split()[:2])

                if not woke and not vosk_wake:
                    maybe = self._maybe_wake(text) or grammar_hit
                    if not (cloud and maybe and self._cloud_check_allowed()):
                        continue  # no wake word: ignore this sentence
                # "Jarvis" alone is the one thing the offline model hears reliably; Whisper tends to
                # invent a sentence for it ("J'ai une petite question"), so trust Vosk here.
                if cloud is not None and not (vosk_wake and not vosk_after):
                    # Spelling hint "Jarvis" only while waiting for the name (see GroqWhisper.transcribe).
                    spoken = cloud.transcribe(audio, wake_hint=not woke or vosk_wake or grammar_hit)
                    if spoken is not None:  # the cloud answered (None = failure -> offline text below)
                        found, after = self._split_wake_text(spoken)
                        if after and self._only_names(after):
                            after = ""  # "Jarvis. Jarvis." is a call, not a question
                        if not found and not woke and self._maybe_wake(text):
                            # The offline model heard a sound-alike of the name and Whisper wrote
                            # "<one or two words>, <command>" ("Texte, ouvre Chrome" for "Apex, ouvre
                            # Chrome"): the words before the comma are the badly heard name.
                            head, sep, rest = spoken.partition(",")
                            if sep and len(head.split()) <= 2 and rest.strip(" ,.!?;:-"):
                                found, after = True, rest.strip(" ,.!?;:-")
                        if not found and not woke:
                            found, after = self._dropped_name(text, spoken, heard if self._wake_rec is not None else "")
                            if found:
                                log.info("Name dropped by Whisper, offline model heard it: %r", text)
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
                        if woke and not after and not vosk_wake and len(text.split()) >= 2                                 and not self._maybe_wake(text):
                            # Whisper returned only the name (or nothing) for a real sentence that the
                            # offline model heard: trust the offline text instead of dropping it.
                            log.info("Whisper gave %r, using the offline text %r", spoken, text)
                            after = text
                        if not after and (found or vosk_wake):
                            woke, deadline = True, now + command_timeout
                            if on_wake:
                                on_wake(False)
                            continue
                        if not after:
                            continue  # silence or noise
                        if on_wake and not woke:
                            on_wake(True)
                        alt = vosk_after if vosk_wake else text
                        self.last_alternative = alt if alt and alt != after.lower() else None
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
        last_partial = ""
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
                        if not text and not final_text and not last_partial:
                            continue  # empty result right after the trigger: keep listening
                        final_text = " ".join(x for x in (final_text, text) if x) or last_partial
                        break
                    loud = max((abs(v) for c in chunks[-20:] for v in array.array("h", c[: len(c) - len(c) % 2])[::16]),
                               default=0) / 327.68 >= self.min_level_follow
                    if text and loud and not is_echo(text.split()):
                        triggered, trigger_time, final_text = True, time.monotonic(), text
                        on_trigger()
                        break
                    chunks, speech_start = [], None
                else:
                    partial = json.loads(self._rec.PartialResult()).get("partial", "").strip()
                    if partial and speech_start is None:
                        speech_start = len(chunks) - 1
                    if partial and triggered:
                        last_partial = partial
                    loud = max((abs(v) for c in chunks[-8:] for v in array.array("h", c[: len(c) - len(c) % 2])[::16]),
                               default=0) / 327.68 >= self.min_level_follow
                    if partial and not triggered and loud and not is_echo(partial.split()):
                        triggered, trigger_time, last_partial = True, time.monotonic(), partial
                        log.info("Barge-in: %r", partial)
                        on_trigger()
        finally:
            self.mute()
        if not triggered:
            return None
        audio = b"".join(chunks[max(0, (speech_start or 0) - 5):])
        cloud = self.transcriber if (self.transcriber is not None and self.transcriber.available()) else None
        final_text = final_text or last_partial
        if cloud is not None:
            spoken = cloud.transcribe(audio, wake_hint=False)
            if spoken and not self._only_names(spoken):
                final_text = spoken
        found, after = self._split_wake_text(final_text)
        result = (after if found else final_text).strip() or None
        log.info("Barge-in sentence: %r", result)
        return result

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
