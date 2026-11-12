"""Text-to-speech.

Main engine: edge-tts (Microsoft neural voices) over a *persistent, pre-warmed* websocket.
Opening a connection costs ~1 s; reusing one brings the first audio down to ~0.4 s.
Audio is played as soon as the first MP3 chunk arrives, sentence by sentence, while Claude
is still writing the rest of the answer.

Fallback engine: pyttsx3 (Windows SAPI5 voices), used automatically when edge-tts fails
(no internet, service down).
"""
from __future__ import annotations

import asyncio
import queue
import re
import threading
import time
from collections.abc import Callable, Iterable, Iterator

from jarvis.audio_out import AudioOutputError, Mp3StreamPlayer
from jarvis.logger import get_logger

log = get_logger(__name__)

CONNECT_TIMEOUT = 4.0      # seconds to open the websocket
RECEIVE_TIMEOUT = 6.0      # max silence between two messages of one answer
IDLE_RECONNECT = 30.0      # pre-warm reopens connections idle for longer than this
OFFLINE_COOLDOWN = 8.0     # after a failure, use the offline voice for this long


class EdgeTTSFailure(Exception):
    pass


# --------------------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------------------
_MARKDOWN = re.compile(r"[*_#`~>|]+")
_URL = re.compile(r"https?://\S+")
_SPACES = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"[.!?…]+[\"»)\]]?\s")


def clean_for_speech(text: str) -> str:
    text = _URL.sub(" le lien ", text)
    text = _MARKDOWN.sub(" ", text)
    return _SPACES.sub(" ", text).strip()


def iter_sentences(chunks: Iterable[str], first_max: int = 70, next_max: int = 450) -> Iterator[str]:
    """Group streamed text into speakable pieces as early as possible.

    A piece ends at a sentence end; a long piece is cut at its last comma so the
    first words can be spoken before the whole sentence is written.
    """
    buffer = ""
    first = True
    for chunk in chunks:
        buffer += chunk
        while True:
            limit = first_max if first else next_max
            match = _SENTENCE_END.search(buffer)
            if match:
                cut = match.end()
            elif len(buffer) > limit and buffer.rfind(", ", 0, limit) > 15:
                cut = buffer.rfind(", ", 0, limit) + 2
            else:
                break
            piece = clean_for_speech(buffer[:cut])
            buffer = buffer[cut:]
            if piece:
                first = False
                yield piece
    piece = clean_for_speech(buffer)
    if piece:
        yield piece


# --------------------------------------------------------------------------------------
# edge-tts persistent session (runs on a private asyncio loop)
# --------------------------------------------------------------------------------------
class EdgeSession:
    def __init__(self, voice: str, rate: str, pitch: str, volume: str):
        from edge_tts.data_classes import TTSConfig

        self.tts_config = TTSConfig(voice, rate, volume, pitch, "SentenceBoundary")
        self.params = {"voice": voice, "rate": rate, "volume": volume, "pitch": pitch}  # as in config.json
        self._session = None
        self._ws = None
        self._last_used = 0.0
        self._lock: asyncio.Lock | None = None

    async def _close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                # Do not wait long for the server's close handshake.
                await asyncio.wait_for(ws.close(), 1.0)
            except Exception:  # noqa: BLE001
                pass

    async def shutdown(self) -> None:
        await self._close()
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _connect(self) -> None:
        import aiohttp
        from edge_tts import communicate as ec
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.drm import DRM

        await self._close()
        if self._session is None:
            self._session = aiohttp.ClientSession(trust_env=True)
        started = time.perf_counter()
        for attempt in (1, 2):
            try:
                self._ws = await asyncio.wait_for(
                    self._session.ws_connect(
                        f"{WSS_URL}&ConnectionId={ec.connect_id()}"
                        f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
                        compress=15, headers=DRM.headers_with_muid(WSS_HEADERS), ssl=ec._SSL_CTX,
                    ),
                    CONNECT_TIMEOUT,
                )
                break
            except aiohttp.WSServerHandshakeError as exc:
                # 403 usually means the PC clock is off: edge-tts can correct for it once.
                if exc.status == 403 and attempt == 1:
                    DRM.handle_client_response_error(exc)
                    continue
                raise
        await self._ws.send_str(
            f"X-Timestamp:{ec.date_to_string()}\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n\r\n"
            '{"context":{"synthesis":{"audio":{"metadataoptions":{'
            '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
            '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n'
        )
        self._last_used = time.monotonic()
        log.info("edge-tts connected in %.2fs", time.perf_counter() - started)

    async def synth_fresh(self, text: str, on_audio: Callable[[bytes], None]) -> None:
        """Same voice through edge-tts's own one-shot connection (used when the persistent
        connection keeps failing): slower to start, but very reliable."""
        import edge_tts

        p = self.params
        got = False
        stream = edge_tts.Communicate(text, p["voice"], rate=p["rate"], volume=p["volume"], pitch=p["pitch"]).stream()
        async for chunk in stream:
            if chunk["type"] == "audio" and chunk["data"]:
                got = True
                on_audio(chunk["data"])
        if not got:
            raise EdgeTTSFailure("no audio received")

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def prewarm(self) -> None:
        async with self._get_lock():
            try:
                if self._ws is None or self._ws.closed or time.monotonic() - self._last_used > IDLE_RECONNECT:
                    await self._connect()
            except Exception as exc:  # noqa: BLE001
                log.warning("edge-tts pre-warm failed: %r", exc)
                await self._close()

    async def synth(self, text: str, on_audio: Callable[[bytes], None]) -> None:
        import aiohttp
        from xml.sax.saxutils import escape

        from edge_tts import communicate as ec

        ssml = ec.mkssml(self.tts_config, escape(ec.remove_incompatible_characters(text)))
        async with self._get_lock():
            for attempt in (1, 2):
                got_audio = False
                try:
                    if self._ws is None or self._ws.closed:
                        await self._connect()
                    await self._ws.send_str(ec.ssml_headers_plus_data(ec.connect_id(), ec.date_to_string(), ssml))
                    while True:
                        msg = await asyncio.wait_for(self._ws.receive(), RECEIVE_TIMEOUT)
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            if "Path:turn.end" in msg.data:
                                self._last_used = time.monotonic()
                                if not got_audio:
                                    raise EdgeTTSFailure("no audio received (check voice name in config.json)")
                                return
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            header_len = int.from_bytes(msg.data[:2], "big")
                            headers = msg.data[2:2 + header_len]
                            data = msg.data[2 + header_len:]
                            if b"Path:audio" in headers and data:
                                got_audio = True
                                on_audio(data)
                        else:  # CLOSE, CLOSING, CLOSED, ERROR
                            raise ConnectionError(f"websocket closed ({msg.type.name})")
                except EdgeTTSFailure:
                    await self._close()
                    raise
                except (aiohttp.ClientError, asyncio.TimeoutError, ConnectionError, OSError) as exc:
                    await self._close()
                    if got_audio or attempt == 2:
                        raise EdgeTTSFailure(f"{exc.__class__.__name__}: {exc}") from exc
                    log.info("edge-tts connection was stale, reconnecting")


# --------------------------------------------------------------------------------------
# Offline fallback (pyttsx3 / SAPI5) on its own COM thread
# --------------------------------------------------------------------------------------
class OfflineVoice:
    def __init__(self, rate: int = 165, language_hint: str = "fr"):
        self.rate = rate
        self.language_hint = language_hint.lower()
        self.voice_name = ""
        self.error: str = ""
        self._queue: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        threading.Thread(target=self._worker, name="offline-tts", daemon=True).start()

    def _worker(self) -> None:
        engine = None
        try:
            import comtypes

            comtypes.CoInitialize()
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", self.rate)
            for voice in engine.getProperty("voices"):
                langs = " ".join(str(x) for x in (voice.languages or [])).lower()
                if self.language_hint in langs or self.language_hint in voice.id.lower():
                    engine.setProperty("voice", voice.id)
                    self.voice_name = voice.name
                    break
            else:
                self.voice_name = "default (no French voice installed)"
        except Exception as exc:  # noqa: BLE001
            self.error = f"{exc.__class__.__name__}: {exc}"
            log.error("Offline voice unavailable: %s", self.error)
        finally:
            self._ready.set()
        while True:
            text, done = self._queue.get()
            if text is None:
                break
            try:
                if engine is not None:
                    engine.say(text)
                    engine.runAndWait()
            except Exception as exc:  # noqa: BLE001
                log.error("Offline voice failed: %r", exc)
            finally:
                done.set()

    def available(self, timeout: float = 5.0) -> bool:
        self._ready.wait(timeout)
        return self._ready.is_set() and not self.error

    def say(self, text: str) -> bool:
        if not self.available():
            return False
        done = threading.Event()
        self._queue.put((text, done))
        done.wait(5 + len(text) * 0.15)
        return True


# --------------------------------------------------------------------------------------
# Public speaker
# --------------------------------------------------------------------------------------
class Speaker:
    def __init__(self, cfg: dict):
        vcfg = cfg["voice"]
        self.cfg = vcfg
        self.output_device = None
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, name="tts-loop", daemon=True).start()
        # edge-tts (and aiohttp) take ~2 s to import: the session is created on first use.
        self._edge_obj: EdgeSession | None = None
        self._edge_en_obj: EdgeSession | None = None   # English voice (answers in English)
        self.language = "fr"                            # set by the assistant for each turn
        self._edge_error = ""
        self._edge_created = False
        self._edge_lock = threading.Lock()
        self._offline: OfflineVoice | None = None
        self._offline_until = 0.0
        self._current: Mp3StreamPlayer | None = None
        self._stop = threading.Event()
        self.last_engine = ""
        self.first_audio_delay: float | None = None
        self.on_audio_start: Callable[[], None] | None = None  # called when sound starts (HUD)

    @property
    def _edge(self) -> EdgeSession | None:
        with self._edge_lock:
            if not self._edge_created:
                self._edge_created = True
                v = self.cfg
                try:
                    self._edge_obj = EdgeSession(v["voice"], v["rate"], v["pitch"], v["volume"])
                except Exception as exc:  # noqa: BLE001 - bad voice settings must not stop Jarvis
                    self._edge_error = f"invalid voice settings: {exc}"
                    log.error("edge-tts disabled: %s", self._edge_error)
            return self._edge_obj

    def _edge_for(self, language: str) -> EdgeSession | None:
        """The French voice, or the English one for answers in English (if configured)."""
        if language == "en" and self.cfg.get("voice_en"):
            if self._edge_en_obj is None:
                v = self.cfg
                try:
                    self._edge_en_obj = EdgeSession(v["voice_en"], v.get("rate_en", v["rate"]),
                                                    v.get("pitch_en", v["pitch"]), v["volume"])
                except Exception as exc:  # noqa: BLE001
                    log.error("English voice disabled: %r", exc)
                    return self._edge
            return self._edge_en_obj
        return self._edge

    # -- helpers -------------------------------------------------------------------
    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def _offline_voice(self) -> OfflineVoice:
        if self._offline is None:
            self._offline = OfflineVoice(int(self.cfg["offline_rate"]), self.cfg["offline_language"])
        return self._offline

    def edge_usable(self) -> bool:
        return self._edge is not None and time.monotonic() >= self._offline_until

    @property
    def level(self) -> float:
        player = self._current
        return player.level if player else 0.0

    # -- API -----------------------------------------------------------------------
    def prewarm(self, wait: bool = False) -> bool:
        """Open the edge-tts connection (in the background unless wait=True).
        Returns True when wait=True and the connection is open."""
        if not self.edge_usable():
            return False
        future = asyncio.run_coroutine_threadsafe(self._edge.prewarm(), self._loop)
        if not wait:
            return False
        try:
            future.result(CONNECT_TIMEOUT * 2 + 1)
        except Exception:  # noqa: BLE001
            return False
        ws = self._edge._ws
        return ws is not None and not ws.closed

    def _audio_started(self) -> None:
        if self.first_audio_delay is None and self.on_audio_start is not None:
            try:
                self.on_audio_start()
            except Exception:  # noqa: BLE001
                log.exception("on_audio_start callback failed")

    def stop(self) -> None:
        self._stop.set()
        player = self._current
        if player:
            player.stop()

    def speak(self, text: str) -> str:
        return self.speak_stream([text])

    def speak_stream(self, chunks: Iterable[str], on_text: Callable[[str], None] | None = None) -> str:
        """Speak text as it streams in. Returns the engine used ("edge"/"offline"/"none").

        If `chunks` raises (e.g. a Claude error), the audio already queued is played,
        then the exception is re-raised for the caller to handle.
        """
        self._stop.clear()
        started = time.perf_counter()
        self.first_audio_delay = None

        def tee(source):
            for chunk in source:
                if on_text:
                    on_text(chunk)
                yield chunk

        player: Mp3StreamPlayer | None = None
        fallback = bool(self.cfg.get("offline_fallback", False))
        engine = "edge" if (self.edge_usable() or not fallback) else "offline"
        edge = self._edge_for(self.language) or self._edge
        error: BaseException | None = None
        try:
            for sentence in iter_sentences(tee(chunks)):
                if self._stop.is_set():
                    break
                if not any(ch.isalnum() for ch in sentence):
                    continue
                if engine == "edge":
                    if player is None:
                        player = Mp3StreamPlayer(self.output_device)
                        self._current = player

                    def on_audio(data: bytes, _p=player):
                        if self.first_audio_delay is None:
                            self._audio_started()
                            self.first_audio_delay = time.perf_counter() - started
                        _p.feed(data)

                    try:
                        self._run(edge.synth(sentence, on_audio), CONNECT_TIMEOUT * 2 + RECEIVE_TIMEOUT * 3)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        log.info("edge-tts persistent connection failed (%r), using a fresh connection", exc)
                    try:
                        self._run(edge.synth_fresh(sentence, on_audio), 20)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        if not fallback:
                            # No other voice: the text stays on screen; try again with the next sentence.
                            log.warning("edge-tts could not say %r (%r); text shown only", sentence[:60], exc)
                            continue
                        log.warning("edge-tts failed, switching to the offline voice: %r", exc)
                        self._offline_until = time.monotonic() + OFFLINE_COOLDOWN
                        engine = "offline"
                        player.finish()
                        player.wait(30)
                if self.first_audio_delay is None:
                    self._audio_started()
                    self.first_audio_delay = time.perf_counter() - started
                self._offline_voice().say(sentence)
        except BaseException as exc:  # noqa: BLE001 - re-raised below after playback
            error = exc
        finally:
            if player is not None:
                player.finish()
                player.wait(60)
                if player.error and isinstance(player.error, AudioOutputError):
                    log.error("Speaker error: %s", player.error)
                player.close()
            self._current = None
        if error is not None:
            raise error
        self.last_engine = engine
        return engine

    def close(self) -> None:
        if self._edge_obj is not None:
            try:
                self._run(self._edge_obj.shutdown(), 2)
            except Exception:  # noqa: BLE001
                pass
        self._loop.call_soon_threadsafe(self._loop.stop)
