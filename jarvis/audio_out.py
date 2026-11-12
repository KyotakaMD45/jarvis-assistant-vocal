"""Audio output: a streaming PCM player, an incremental MP3 decoder, and short UI tones.

Everything runs on small background threads so playback starts as soon as the first
bytes arrive. `level` exposes the current output volume (0..1) for a future waveform view.
"""
from __future__ import annotations

import array
import math
import threading
from collections import deque

from jarvis.logger import get_logger

log = get_logger(__name__)

SAMPLE_RATE = 24000  # edge-tts sends 24 kHz mono MP3
FRAME_BYTES = 2      # signed 16-bit mono


class AudioOutputError(Exception):
    """Raised when no output device can be opened."""


class PcmPlayer:
    """Plays 16-bit mono PCM fed from any thread. Silence is played while waiting for data."""

    def __init__(self, sample_rate: int = SAMPLE_RATE, device_id=None):
        import miniaudio

        self.sample_rate = sample_rate
        self._chunks: deque[bytes] = deque()
        self._pending = b""
        self._lock = threading.Lock()
        self._finished = False   # no more data will be fed
        self._stopped = False    # playback was interrupted
        self.done = threading.Event()
        self.level = 0.0
        self.played_frames = 0
        self._drain_frames = 0
        self._started_sound = threading.Event()
        try:
            self._device = miniaudio.PlaybackDevice(
                output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                sample_rate=sample_rate, buffersize_msec=100, device_id=device_id,
            )
            generator = self._generator()
            next(generator)
            self._device.start(generator)
        except Exception as exc:  # noqa: BLE001
            raise AudioOutputError(f"Cannot open the speaker/headphones: {exc}") from exc

    # -- producer side -------------------------------------------------------------
    def feed(self, pcm: bytes) -> None:
        if pcm and not self._stopped:
            with self._lock:
                self._chunks.append(bytes(pcm))

    def finish(self) -> None:
        """Signal that no more audio is coming; `done` is set once the buffer drains."""
        self._finished = True

    def stop(self) -> None:
        """Interrupt playback immediately."""
        self._stopped = True
        with self._lock:
            self._chunks.clear()
            self._pending = b""
        self._finished = True

    def wait(self, timeout: float | None = None) -> bool:
        return self.done.wait(timeout)

    def close(self) -> None:
        try:
            self._device.close()
        except Exception:  # noqa: BLE001
            pass

    def has_started(self) -> bool:
        return self._started_sound.is_set()

    # -- device side -----------------------------------------------------------------
    def _take(self, n_bytes: int) -> bytes:
        with self._lock:
            out = bytearray(self._pending)
            while len(out) < n_bytes and self._chunks:
                out += self._chunks.popleft()
            self._pending = bytes(out[n_bytes:])
            return bytes(out[:n_bytes])

    def _generator(self):
        required_frames = yield b""
        while True:
            n_bytes = required_frames * FRAME_BYTES
            data = self._take(n_bytes)
            if data:
                self._started_sound.set()
                samples = array.array("h", data[: len(data) - len(data) % 2])
                self.played_frames += len(samples)
                peak = max(1, max(abs(s) for s in samples[::8]) if samples else 0)
                self.level = min(1.0, peak / 20000)
            else:
                self.level = 0.0
                if self._finished and not self._chunks and not self._pending:
                    # The device still holds buffered audio: wait for it to drain before "done".
                    self._drain_frames += required_frames
                    if self._drain_frames >= self.sample_rate * 0.3 or self._stopped:
                        self.done.set()
            if len(data) < n_bytes:
                data += b"\0" * (n_bytes - len(data))
            required_frames = yield data


class _BlockingSource:
    """A byte source for miniaudio's streaming decoder, fed chunk by chunk from another thread."""

    def __init__(self):
        self._buf = bytearray()
        self._cond = threading.Condition()
        self._closed = False

    def write(self, data: bytes) -> None:
        with self._cond:
            self._buf += data
            self._cond.notify_all()

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def read(self, num_bytes: int) -> bytes:
        # Return as soon as *some* data is available: returning b"" means end of stream.
        with self._cond:
            while not self._buf and not self._closed:
                self._cond.wait(0.5)
            out = bytes(self._buf[:num_bytes])
            del self._buf[:num_bytes]
            return out


class Mp3StreamPlayer:
    """Feed MP3 bytes as they arrive; decoding and playback start with the first chunk.

    The output device is opened in the background (~0.3 s) while the first audio is
    still being fetched, so opening it adds no delay.
    """

    def __init__(self, device_id=None):
        self.player: PcmPlayer | None = None
        self.error: Exception | None = None
        self._source = _BlockingSource()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = False
        threading.Thread(target=self._open, args=(device_id,), name="audio-open", daemon=True).start()

    def _open(self, device_id) -> None:
        try:
            self.player = PcmPlayer(SAMPLE_RATE, device_id)
        except AudioOutputError as exc:
            self.error = exc
            log.error("%s", exc)
        finally:
            self._ready.set()

    def feed(self, mp3: bytes) -> None:
        self._source.write(mp3)
        if self._thread is None:
            self._thread = threading.Thread(target=self._decode, name="mp3-decoder", daemon=True)
            self._thread.start()

    def _decode(self) -> None:
        import miniaudio

        class _Source(miniaudio.StreamableSource):
            def __init__(self, inner):
                self.inner = inner

            def read(self, num_bytes: int) -> bytes:
                return self.inner.read(num_bytes)

        # miniaudio only keeps a cffi handle to the source (a reference cycle); keep a strong
        # reference for the whole decode, or the garbage collector frees it mid-stream (hard crash).
        self._ma_source = _Source(self._source)
        try:
            stream = miniaudio.stream_any(
                self._ma_source, source_format=miniaudio.FileFormat.MP3,
                output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1,
                sample_rate=SAMPLE_RATE, frames_to_read=2048,
            )
            self._ready.wait(5)
            for samples in stream:
                if self.player is not None:
                    self.player.feed(samples.tobytes())
        except Exception as exc:  # noqa: BLE001
            self.error = exc
            log.error("MP3 decoding failed: %r", exc)
        finally:
            if self.player is not None:
                self.player.finish()

    def finish(self) -> None:
        self._source.close()
        if self._thread is None:
            self._ready.wait(5)
            if self.player is not None:
                self.player.finish()

    def wait(self, timeout: float | None = None) -> bool:
        self._ready.wait(5)
        if self.player is None:
            return True
        return self.player.wait(timeout)

    def stop(self) -> None:
        self._source.close()
        if self.player is not None:
            self.player.stop()

    def close(self) -> None:
        self._ready.wait(5)
        if self.player is not None:
            self.player.close()

    def has_started(self) -> bool:
        return self.player is not None and self.player.has_started()

    @property
    def level(self) -> float:
        return self.player.level if self.player is not None else 0.0


def tone_pcm(freqs: list[tuple[float, float]], volume: float = 0.25, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Build a short tone sequence [(frequency_hz, seconds), ...] with soft fade in/out."""
    samples = array.array("h")
    for freq, seconds in freqs:
        n = int(sample_rate * seconds)
        fade = max(1, int(sample_rate * 0.01))
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)
            samples.append(int(32767 * volume * env * math.sin(2 * math.pi * freq * i / sample_rate)))
    return samples.tobytes()


WAKE_TONE = [(880, 0.07), (1320, 0.09)]
TEST_TONE = [(660, 0.15), (880, 0.15)]


def sweep_pcm(segments, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Synthesize "sci-fi" UI sounds.

    segments: [(start_hz, end_hz, seconds, volume, shimmer), ...] - each segment glides
    from start_hz to end_hz, adds a soft octave harmonic, and optional tremolo (shimmer).
    """
    samples = array.array("h")
    for f0, f1, seconds, volume, shimmer in segments:
        n = max(1, int(sample_rate * seconds))
        attack = max(1, int(sample_rate * 0.008))
        phase = 0.0
        for i in range(n):
            x = i / n
            freq = f0 + (f1 - f0) * x
            phase += 2 * math.pi * freq / sample_rate
            env = min(1.0, i / attack) * (1 - x) ** 1.6
            trem = 1 - shimmer * 0.5 * (1 + math.sin(2 * math.pi * 22 * i / sample_rate))
            value = math.sin(phase) + 0.3 * math.sin(2 * phase) + 0.12 * math.sin(3.01 * phase)
            samples.append(int(32767 * volume * env * trem * value / 1.42))
    return samples.tobytes()


FX = {
    "wake": [(900, 1350, 0.06, 0.22, 0.0), (1350, 1900, 0.09, 0.2, 0.0)],
    "reply": [(1250, 820, 0.09, 0.12, 0.0)],
    "startup": [(180, 760, 0.55, 0.22, 0.35), (760, 1180, 0.25, 0.16, 0.2), (1320, 1320, 0.45, 0.12, 0.0)],
    "error": [(520, 300, 0.18, 0.18, 0.0)],
}
_fx_cache: dict[str, bytes] = {}


def play_pcm(pcm: bytes, wait: bool = False, device_id=None) -> bool:
    """Play raw 24 kHz PCM. Never raises; returns False if the speaker is unavailable."""
    try:
        player = PcmPlayer(SAMPLE_RATE, device_id)
    except AudioOutputError as exc:
        log.warning("Sound not played: %s", exc)
        return False
    player.feed(pcm)
    player.finish()

    def _close_when_done():
        player.wait(5)
        player.close()

    if wait:
        _close_when_done()
    else:
        threading.Thread(target=_close_when_done, daemon=True).start()
    return True


def play_fx(name: str, wait: bool = False) -> bool:
    if name not in _fx_cache:
        _fx_cache[name] = sweep_pcm(FX[name])
    return play_pcm(_fx_cache[name], wait=wait)


def play_tone(freqs=WAKE_TONE, volume: float = 0.25, wait: bool = False, device_id=None) -> bool:
    """Play a short tone. Never raises; returns False if the speaker is unavailable."""
    return play_pcm(tone_pcm(freqs, volume), wait=wait, device_id=device_id)
