# J.A.R.V.I.S. — voice assistant for Windows

A fast, lightweight French voice assistant for Windows 10/11 with a futuristic HUD, built to run
smoothly on a modest laptop (tested on an HP ProBook 650 G4: i7-8550U, 8 GB RAM, Intel UHD 620).

- **Wake word "Jarvis"** detected offline (Vosk), sentence transcribed by **Groq Whisper** (accurate),
  with automatic offline fallback.
- **Natural conversation**: answers stream as speech sentence by sentence, follow-up questions
  without repeating "Jarvis", and you can **interrupt Jarvis while he talks** (barge-in).
- **Several AI brains**: Claude, Groq, Gemini or OpenAI — switch by voice ("passe sur Groq").
- **Controls the PC**: open/close apps and folders, web search, music and media keys, volume,
  brightness, screenshots, reminders and timers, lock / sleep / shutdown (with spoken confirmation).
- **Voice**: Microsoft neural voice (edge-tts, deep "Henri" voice, pitch/rate configurable) with an
  offline Windows voice fallback.
- **Futuristic HUD** (HTML canvas in a WebView2 window, no Electron): glowing core, light waves,
  live voice waveform, 30 FPS cap, low power mode.
- **Runs in the background** with a tray icon; single instance; restart / quit from the tray.

![HUD](reference_ui.png)

## Quick start (Windows)

1. Download or clone this repository, e.g. into `C:\JARVIS`.
2. Double-click **`install.bat`** — installs Python 3.12 if needed, the dependencies and the French
   speech model (~41 MB), then asks for a Claude API key (press Enter to skip).
3. Add at least one AI key:
   - Groq (free tier, fast, also enables the accurate cloud speech recognition):
     `start.bat --setup-key groq` — key from https://console.groq.com/keys
   - or Claude: `start.bat --setup-key claude`, Gemini: `--setup-key gemini`, OpenAI: `--setup-key openai`.
4. Double-click **`test.bat`** to check microphone, speaker, internet and keys.
5. Double-click **`start.bat`** and say **"Jarvis, quelle heure est-il ?"**.

Keys are stored in `.env` (never committed). Stop Jarvis with `stop.bat` or the tray icon.

### Démarrage rapide (FR)

`install.bat` → `start.bat --setup-key groq` → `test.bat` → `start.bat`, puis dites « Jarvis, … ».
Cliquez sur le micro doré (ou appuyez sur Espace) pour parler sans dire « Jarvis ».
Vous pouvez couper la parole à Jarvis quand il répond.

## Using it

| Say / do | Effect |
|---|---|
| "Jarvis, ouvre WhatsApp" / "ferme la calculatrice" | open / close apps, folders, sites |
| "Jarvis, écris un code Python qui affiche bonjour dans VS Code" | the AI opens VS Code, creates a file and types the code |
| "écris bonjour à tous", "copie ça", "colle", "enregistre", "sélectionne tout" | typing and shortcuts in the active window |
| "nouvel onglet", "ferme l'onglet", "actualise", "descends", "plein écran" | browser / page control |
| "réduis la fenêtre", "mets la fenêtre à gauche", "affiche le bureau", "change de fenêtre" | window management |
| "ouvre les paramètres du Wi-Fi", "passe en mode sombre" | Windows settings |
| "utilisation du processeur", "espace libre sur le disque", "mon adresse IP" | system information |
| "cherche le fichier rapport", "vide la corbeille" (asks first) | files |
| "Jarvis, cherche la météo de Paris" | web search |
| "Jarvis, mets le volume à 30 %", "coupe le son" | volume |
| "Jarvis, joue du Daft Punk sur YouTube", "pause", "chanson suivante" | music |
| "Jarvis, rappelle-moi dans 10 minutes de sortir le gâteau", "minuteur de 5 minutes" | reminders |
| "Jarvis, passe sur Groq / Claude / Gemini / OpenAI" | change the AI |
| "Jarvis, éteins l'ordinateur" | asks "oui / non" first, 15 s to cancel |
| "Jarvis, que sais-tu faire ?" | help |
| Gold mic button or **Space** | talk without the wake word |
| Talk while Jarvis answers | interrupts him |
| SYS / WEB / MEDIA / REPEAT / SETTINGS | status + log + keyboard input / web search / play-pause / repeat last answer / AI + mic + display |

## Configuration — `config.json`

- `ai`: active provider, models, system prompt (personality), answer length, timeouts.
- `voice`: `fr-FR-HenriNeural`, `pitch` (`-25Hz`), `rate` (`-5%`) — `start.bat --voice-test` to hear it.
- `listening`: wake words, microphone, `cloud_transcription` (`groq`/`off`), `barge_in`, follow-up time.
- `hud`: `low_power`, `fps`, `fullscreen`, `sounds`.

## Add a command

Copy `jarvis/commands/_template.py` to a new file in `jarvis/commands/`, write the function that
returns the sentence to say, give it French trigger patterns (and a description so the AI can call it
as a tool), then restart Jarvis. Nothing else to register.

## Project layout

```
install.bat start.bat stop.bat test.bat   one-click scripts
config.json                                settings
jarvis/
  app.py runtime.py tray.py instance.py   entry point, background mode, tray, single instance
  voice.py                                 conversation loop (wake word, commands, AI, barge-in)
  stt.py cloud_stt.py                      speech recognition (Vosk offline + Groq Whisper)
  tts.py audio_out.py                      speech synthesis (edge-tts streaming) and audio
  brain.py providers/                      AI providers (Claude, Groq, Gemini, OpenAI) + tool calls
  commands/                                one file per command family
  hud/ hud_server.py hud_window.py ui.py   the HUD and its live event stream
  diagnostics.py config.py ...             self-test, settings, helpers
```

Logs: `jarvis.log`. Requirements: Windows 10/11, Python 3.10+ (installed automatically), a microphone.
