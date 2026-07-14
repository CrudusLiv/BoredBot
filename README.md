# Vesper

Vesper is a local-first personal voice assistant. It listens for a wake word (or push-to-talk), transcribes speech, routes it through an LLM of your choice, and speaks back — all through a Three.js orb UI in the browser.

---

## Install

```powershell
git clone https://github.com/CrudusLiv/Vesper.git
cd Vesper
pip install -e ".[core]"
```

That installs the full working voice app: web/async stack (FastAPI, uvicorn), speech-to-text (faster-whisper, vosk, openwakeword), text-to-speech (edge-tts), audio I/O, and the setup UI.

Optional dependency groups:

```powershell
# Offline, higher-quality neural TTS (~300 MB model download on first use)
pip install -e ".[core,tts-kokoro]"

# Everything needed to build the Windows .exe
pip install -e ".[core,build]"
```

## Run

```powershell
py -m voice              # wake-word mode (default) — say "vesper" to trigger
py -m voice --voice      # push-to-talk instead of wake word
py -m voice --smoke-test # import every module and exit — no audio hardware needed
py -m voice --version    # print the installed version
```

Open `http://localhost:7070` (Edge `--app` mode recommended) for the orb UI, if `ui_enabled` is set in `voice/config.json`. The HUD is a galaxy/atomic motif around the orb — rounded glass panels, a drifting parallax starfield, and orbiting status indicators — with state/usage readouts on the left and a **Modules** button (bottom-right) for chat, notices, finance, calendar, jobs, workspace, apps, profiles, and settings.

Scroll down (or press →) to dock the orb into the corner and maximize the notices feed into a centered panel; scroll up, press ←, or hit Esc to bring the orb back.

## First run

The first launch opens a small setup wizard (identity, LLM backend, optional API keys, voice/wake-word settings). It writes your choices to `%APPDATA%/Vesper/config.json` (which overrides the repo's `voice/config.json` defaults) and marks setup complete so it won't run again.

Vesper can run with **no API keys at all**:

- **Speech-to-text** — `faster-whisper` runs fully local and offline (installed with the `core` group).
- **Text-to-speech** — `edge-tts` is the default engine: free, no API key, requires an internet connection.
- **LLM** — auto-detects, in priority order, a local Ollama server, a local LM Studio server, the `ANTHROPIC_API_KEY` env var, then falls back to the `claude` CLI subprocess. So it needs *either* a local model server running, *or* the `claude` CLI installed and authenticated, *or* an Anthropic API key — one of the three, not all.

Optional upgrades: an `ANTHROPIC_API_KEY` for the Anthropic API backend, an `ELEVENLABS_API_KEY` for higher-quality (paid) TTS, or the `tts-kokoro` extra for offline neural TTS.

## Build the Windows executable

```powershell
pip install -e ".[core,build]"
pyinstaller voice.spec
```

`voice.spec` bundles the app as a windowed (no console) single executable. Model files (Whisper/Vosk/openwakeword weights) are not bundled — they download to the user's cache on first run, keeping the installer small. See the comments in `voice.spec` for PyInstaller-specific gotchas.

## License

MIT — see [LICENSE](LICENSE).
