"""Self-test: checks each layer in order and says exactly what fails and how to fix it."""
from __future__ import annotations

import socket
import sys
import time

from jarvis.api_key import get_api_key, looks_like_key, mask
from jarvis.logger import get_logger

log = get_logger(__name__)

API_HOST = "api.anthropic.com"


class Report:
    def __init__(self) -> None:
        self.failures = 0

    def ok(self, name: str, detail: str = "") -> None:
        print(f"  [ OK ]  {name}" + (f" - {detail}" if detail else ""))
        log.info("TEST OK   %s %s", name, detail)

    def fail(self, name: str, detail: str, fix: str = "") -> None:
        self.failures += 1
        print(f"  [FAIL]  {name} - {detail}")
        if fix:
            print(f"          -> {fix}")
        log.error("TEST FAIL %s: %s", name, detail)

    def warn(self, name: str, detail: str) -> None:
        print(f"  [WARN]  {name} - {detail}")
        log.warning("TEST WARN %s: %s", name, detail)

    def skip(self, name: str, reason: str) -> None:
        print(f"  [SKIP]  {name} - {reason}")


def _check_internet(report: Report) -> bool:
    try:
        ip = socket.gethostbyname(API_HOST)
    except OSError as exc:
        # Distinguish "no internet at all" from "DNS only".
        try:
            socket.create_connection(("1.1.1.1", 443), timeout=3).close()
            report.fail("Internet", f"internet works but {API_HOST} cannot be resolved ({exc})",
                        "Check your DNS settings, VPN or firewall.")
        except OSError:
            report.fail("Internet", "no internet connection", "Connect to Wi-Fi or Ethernet, then run the test again.")
        return False
    try:
        start = time.perf_counter()
        socket.create_connection((ip, 443), timeout=5).close()
        report.ok("Internet", f"{API_HOST} reachable in {(time.perf_counter() - start) * 1000:.0f} ms")
        return True
    except OSError as exc:
        report.fail("Internet", f"{API_HOST} resolved but port 443 is blocked ({exc})",
                    "A firewall, antivirus or proxy is blocking the connection.")
        return False


def _check_speaker(report: Report) -> None:
    from jarvis.audio_out import TEST_TONE, play_tone

    if play_tone(TEST_TONE, volume=0.3, wait=True):
        report.ok("Speaker", "played two short beeps (if you heard nothing, check the Windows volume)")
    else:
        report.fail("Speaker", "no output device could be opened",
                    "Plug in speakers/headphones or pick an output device in Windows sound settings.")


def _check_microphone(report: Report, cfg: dict) -> None:
    from jarvis.stt import MicError, record_level

    print("          Microphone: recording 2 seconds, say something now...", flush=True)
    try:
        peak, blocks = record_level(2.0, cfg["listening"].get("input_device"))
    except MicError as err:
        report.fail("Microphone", str(err))
        return
    if blocks == 0:
        report.fail("Microphone", "no sound data received", "Check Settings > Privacy > Microphone.")
    elif peak == 0:
        report.fail("Microphone", "the microphone sends pure silence (muted or blocked)",
                    "Unmute it (F8 / sound settings) and allow desktop apps in Settings > Privacy > Microphone.")
    elif peak < 0.02:
        report.warn("Microphone", f"works but the level is very low ({peak:.1%}). Did you speak? "
                    "If yes, raise the microphone volume in Windows sound settings.")
    else:
        report.ok("Microphone", f"works, peak level {peak:.0%}")


def _check_tts(report: Report, cfg: dict, online: bool) -> None:
    from jarvis.tts import OfflineVoice, Speaker

    vcfg = cfg["voice"]
    if online:
        speaker = Speaker(cfg)
        try:
            if speaker._edge is None:
                report.fail("Voice (edge-tts)", speaker._edge_error, "Fix the voice settings in config.json.")
            else:
                received = []
                started = time.perf_counter()
                speaker._run(speaker._edge.synth("Test.", received.append), 20)
                report.ok("Voice (edge-tts)", f"{vcfg['voice']} pitch {vcfg['pitch']} rate {vcfg['rate']}, "
                          f"first audio in {time.perf_counter() - started:.1f}s (incl. connection)")
        except Exception as exc:  # noqa: BLE001
            report.fail("Voice (edge-tts)", f"{exc.__class__.__name__}: {exc}",
                        "Check the voice name in config.json (e.g. fr-FR-HenriNeural) and your internet.")
        finally:
            speaker.close()
    else:
        report.skip("Voice (edge-tts)", "needs internet")

    offline = OfflineVoice(int(vcfg["offline_rate"]), vcfg["offline_language"])
    if not offline.available(10):
        report.fail("Offline voice", offline.error or "SAPI5 did not start",
                    "Only needed without internet. Reinstall with install.bat.")
    elif "no French voice" in offline.voice_name:
        report.warn("Offline voice", "no French Windows voice installed, the offline fallback will use another language")
    else:
        report.ok("Offline voice", f"{offline.voice_name} (used without internet)")


def _check_speech_recognition(report: Report, cfg: dict, online: bool) -> None:
    from jarvis.stt import Listener, MicError

    started = time.perf_counter()
    listener = Listener(cfg)
    try:
        listener.open(use_microphone=False)
    except MicError as err:
        report.fail("Speech model", str(err), "Run install.bat to download it.")
        return
    report.ok("Speech model", f"loaded in {time.perf_counter() - started:.1f}s")
    if not online:
        report.skip("Wake word", "needs internet to generate the test sentence")
        return
    try:
        import asyncio

        import edge_tts
        import miniaudio

        async def synth() -> bytes:
            data = b""
            async for chunk in edge_tts.Communicate("Apex, quelle heure est-il ?", "fr-FR-HenriNeural").stream():
                if chunk["type"] == "audio":
                    data += chunk["data"]
            return data

        pcm = miniaudio.decode(asyncio.run(synth()), output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=16000).samples.tobytes()
        silence = b"\0" * 32000
        listener.feed_pcm_for_test(silence + pcm + silence * 2)
        woke = []
        heard = listener.listen(on_wake=woke.append, should_stop=lambda: listener._audio.empty())
        if woke and heard and "heure" in heard:
            report.ok("Wake word", f"'Apex, quelle heure est-il' -> command '{heard}'")
        else:
            report.fail("Wake word", f"test sentence not understood (heard: {heard!r})",
                        "Check listening.model_path and wake_words in config.json.")
    except Exception as exc:  # noqa: BLE001
        report.warn("Wake word", f"could not run the recognition test ({exc.__class__.__name__}: {exc})")


def run_diagnostics(cfg: dict, config_warnings: list[str], voice: bool = True) -> int:
    """Return 0 when everything passes, 1 otherwise. voice=False skips the audio checks."""
    report = Report()
    from jarvis.brain import Brain, BrainError
    from jarvis.providers import PROVIDERS, create

    brain = Brain(cfg)
    active = brain.provider_name
    print("\nApex self-test\n" + "-" * 40)

    # 1. Python
    if sys.version_info >= (3, 10):
        report.ok("Python", sys.version.split()[0])
    else:
        report.fail("Python", f"version {sys.version.split()[0]} is too old", "Install Python 3.10 or newer, then run install.bat.")

    # 2. Dependencies
    from jarvis.jiter_fallback import ensure_jiter

    if not ensure_jiter():
        report.warn("jiter", "Windows (Smart App Control) blocked this library's DLL: using the built-in fallback")
    try:
        import anthropic
        import openai
        report.ok("AI SDKs", f"anthropic {anthropic.__version__}, openai {openai.__version__}")
    except ImportError as exc:
        report.fail("AI SDKs", f"not installed ({exc.name})", "Run install.bat.")
        print(f"\nResult: {report.failures} problem(s) found. Details in jarvis.log.")
        return 1

    # 3. Config
    if config_warnings:
        for warning in config_warnings:
            report.warn("config.json", warning)
    else:
        report.ok("config.json", f"active AI: {PROVIDERS[active].label} ({brain.model})")

    # 4. Internet
    online = _check_internet(report)

    # 5. Every provider: key present, well formed, accepted, model available.
    print("\n  AI providers (active: " + PROVIDERS[active].label + ")")
    active_ok = False
    for name, info in PROVIDERS.items():
        key, source = get_api_key(name)
        tag = f"{info.label}{' (active)' if name == active else ''}"
        if not key:
            if name == active:
                report.fail(tag, "no API key in .env", f"Run `start.bat --setup-key {name}` (key from {info.keys_url}).")
            else:
                report.skip(tag, f"no key (optional: `start.bat --setup-key {name}`)")
            continue
        if not looks_like_key(key, name):
            report.fail(tag, f"the key from {source} has a wrong format ({mask(key)}), it should start with '{info.key_prefix}'",
                        f"Run `start.bat --setup-key {name}` to re-enter it.")
            continue
        if not online:
            report.skip(tag, f"key {mask(key)} present, cannot check it offline")
            continue
        try:
            model = create(name, cfg["ai"], key).verify()
            report.ok(tag, f"key {mask(key)} accepted, model {model} available")
            active_ok = active_ok or name == active
        except BrainError as err:
            report.fail(tag, err.message, f"Check ai.{name}.model in config.json." if err.kind == "not_found" else "")
        except Exception as exc:  # noqa: BLE001
            report.fail(tag, f"{exc.__class__.__name__}: {exc}")

    # 6. A real streamed answer from the active provider.
    if active_ok:
        start = time.perf_counter()
        try:
            answer = "".join(brain.ask("Réponds seulement par le mot : opérationnel.")).strip()
            report.ok("Test answer", f"\"{answer[:60]}\" in {time.perf_counter() - start:.1f}s")
        except BrainError as err:
            report.fail("Test answer", err.message)
    else:
        report.skip("Test answer", "the active AI provider is not reachable")

    if voice:
        print("\n  Interface")
        try:
            import webview  # noqa: F401

            report.ok("HUD window", "pywebview (WebView2) available"
                      + (", low power mode ON" if cfg["hud"]["low_power"] else ""))
        except Exception as exc:  # noqa: BLE001
            from jarvis.hud_window import EDGE_PATHS

            if any(p.exists() for p in EDGE_PATHS):
                report.warn("HUD window", f"pywebview unavailable ({exc.__class__.__name__}), Edge app mode will be used")
            else:
                report.warn("HUD window", "no window engine found, the HUD will open in your browser")
        print("\n  Audio")
        _check_speaker(report)
        _check_microphone(report, cfg)
        _check_tts(report, cfg, online)
        _check_speech_recognition(report, cfg, online)

    print("-" * 40)
    if report.failures:
        print(f"Result: {report.failures} problem(s) found. Details in jarvis.log.\n")
        return 1
    print("Result: everything works.\n")
    return 0
