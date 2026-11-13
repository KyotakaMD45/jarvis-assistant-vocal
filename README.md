# A.P.E.X. — voice assistant for Windows (French & English)

Apex (formerly Jarvis, then Knull) is a fast, lightweight **bilingual (French / English)** voice assistant for Windows 10/11 with a futuristic HUD, built to run
smoothly on a modest laptop (tested on an HP ProBook 650 G4: i7-8550U, 8 GB RAM, Intel UHD 620).

- **Wake word "Apex"** (also "Knull" or "Jarvis") detected offline (Vosk), sentence transcribed by **Groq Whisper large-v3**
  with automatic French/English detection; answers in the language you speak, with a deep multilingual voice
  (fr-FR-RemyMultilingualNeural). Offline fallback.
- **Natural conversation**: answers stream as speech sentence by sentence, follow-up questions
  without repeating the name, and you can **interrupt Apex while he talks** (barge-in).
- **Several AI brains**: Claude, Groq, Gemini or OpenAI — switch by voice ("passe sur Groq").
- **Controls the PC**: open/close apps and folders, web search, music and media keys, volume,
  brightness, screenshots, reminders and timers, lock / sleep / shutdown (with spoken confirmation).
- **Voice**: Microsoft neural voice (edge-tts, deep "Henri" voice, pitch/rate configurable) with an
  offline Windows voice fallback.
- **Futuristic HUD** (HTML canvas in a WebView2 window, no Electron): glowing core, light waves,
  live voice waveform, 30 FPS cap, low power mode.
- **Runs in the background** with a tray icon; single instance; restart / quit from the tray.
  A watchdog restarts Apex if it ever stops without being asked (native crashes go to `crash.log`).
  "Au revoir" / "bye" only end the conversation; quitting needs "quitte" / "éteins-toi" and a spoken "oui".

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
5. Double-click **`start.bat`** and say **"Apex, quelle heure est-il ?"** or **"Apex, what time is it?"**.

Keys are stored in `.env` (never committed). Stop Apex with `stop.bat` or the tray icon.

### Démarrage rapide (FR)

`install.bat` → `start.bat --setup-key groq` → `test.bat` → `start.bat`, puis dites « Apex, … » (en français ou en anglais).
Cliquez sur le micro doré (ou appuyez sur Espace) pour parler sans dire « Apex ».
Vous pouvez couper la parole à Apex quand il répond.

## iPhone

Say **"Apex, connecte mon iPhone"**: a QR code opens on the PC. Scan it with the iPhone camera (same Wi-Fi)
to get the phone page: live conversation, type or dictate commands, quick buttons, answers read aloud.
The page also explains how to make a **Siri shortcut** ("Dis Siri, Apex") that calls `/api/ask` and reads
Apex's answer. Windows may ask to allow network access the first time: allow **private networks**.
"Apex, déconnecte mon iPhone" stops it and changes the secret key.

## Contacts (messages)

To send WhatsApp messages or emails by name, add your contacts to `config.json`:

```json
"contacts": {
  "paul": {"whatsapp": "+33612345678", "email": "paul@example.com"}
}
```

Without a phone number, Apex searches the name in WhatsApp and opens the first match. A message is
always read back to you and sent only after you say "oui" / "yes".

## Using it

| Say / do | Effect |
|---|---|
| "Apex, ouvre WhatsApp" / "Apex, close the calculator" | open / close apps, folders, sites |
| "Apex, envoie un message à Paul sur WhatsApp : j'arrive" / "send an email to paul@x.com…" | finds the contact on screen (tolerant to spelling), types the message, sends after "oui" / "yes", then checks it left |
| "clique sur Envoyer", "regarde l'écran", "remplis le champ recherche avec…" | uses any app like a person (Windows UI Automation: sees buttons, fields, rows) |
| "résume ce texte", "traduis ça en anglais", "corrige ce texte", "reformule", "explique ce code" | works on the selected text of any app |
| "demande à Claude …", "ask ChatGPT …", "demande à Perplexity …" | opens the site with the question |
| "clique", "double clic", "clic droit" | mouse clicks |
| "Apex, écris un code Python qui affiche bonjour dans VS Code" | the AI opens VS Code, creates a file and types the code |
| "écris bonjour à tous", "copie ça", "colle", "enregistre", "sélectionne tout" | typing and shortcuts in the active window |
| "nouvel onglet", "ferme l'onglet", "actualise", "descends", "plein écran" | browser / page control |
| "réduis la fenêtre", "mets la fenêtre à gauche", "affiche le bureau", "change de fenêtre" | window management |
| "ouvre les paramètres du Wi-Fi", "passe en mode sombre" | Windows settings |
| "utilisation du processeur", "espace libre sur le disque", "mon adresse IP" | system information |
| "cherche le fichier rapport", "vide la corbeille" (asks first) | files |
| "Apex, cherche la météo de Paris" | web search |
| "Apex, mets le volume à 30 %", "coupe le son" | volume |
| "Apex, joue du Daft Punk sur YouTube", "pause", "chanson suivante" | music |
| "Apex, rappelle-moi dans 10 minutes de sortir le gâteau", "minuteur de 5 minutes" | reminders |
| "Apex, passe sur Groq / Claude / Gemini / OpenAI" | change the AI |
| "Apex, éteins l'ordinateur" | asks "oui / non" first, 15 s to cancel |
| "Apex, que sais-tu faire ?" | help |
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
