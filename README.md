# Vesper

Vesper is a local-first personal voice assistant. It listens via push-to-talk, transcribes speech, routes it through an LLM of your choice, and speaks back — all through a Three.js orb UI in the browser.

---

## Install

```powershell
git clone https://github.com/CrudusLiv/Vesper.git
cd Vesper
pip install -e ".[core]"
```

That installs the full working voice app: web/async stack (FastAPI, uvicorn), speech-to-text (faster-whisper), text-to-speech (edge-tts fallback — add `tts-chatterbox` below for the default engine), audio I/O, and the setup UI.

Optional dependency groups:

```powershell
# Chatterbox Turbo — the default TTS engine (local, GPU-accelerated, voice-cloning capable)
pip install -e ".[core,tts-chatterbox]"

# Offline, higher-quality neural TTS (~300 MB model download on first use)
pip install -e ".[core,tts-kokoro]"

# Everything needed to build the Windows .exe
pip install -e ".[core,build]"
```

Without `tts-chatterbox`, Vesper still runs — `voice/tts.py` falls back to edge-tts and prints a warning.

## Run

```powershell
py -m voice              # push-to-talk voice mode (default)
py -m voice --text       # text mode
py -m voice --smoke-test # import every module and exit — no audio hardware needed
py -m voice --version    # print the installed version
```

Open `http://localhost:7070` (Edge `--app` mode recommended) for the orb UI, if `ui_enabled` is set in `voice/config.json`. The HUD is a galaxy/atomic motif around the orb — rounded glass panels, a drifting parallax starfield, and orbiting status indicators — with state/usage readouts on the left and a **Modules** button (bottom-right) for chat, notices, finance, calendar, jobs, workspace, apps, profiles, and settings.

Scroll down (or press →) to dock the orb into the corner and maximize the notices feed into a centered panel; scroll up, press ←, or hit Esc to bring the orb back.

## First run

The first launch opens a small setup wizard (identity, LLM backend, optional API keys, voice settings). It writes your choices to `%APPDATA%/Vesper/config.json` (which overrides the repo's `voice/config.json` defaults) and marks setup complete so it won't run again.

Vesper can run with **no API keys at all**:

- **Speech-to-text** — `faster-whisper` runs fully local and offline (installed with the `core` group).
- **Text-to-speech** — Chatterbox Turbo is the default: local, GPU-accelerated, supports voice cloning from a short reference clip (needs the `tts-chatterbox` extra). Falls back to `edge-tts` (free, no API key, needs internet) if Chatterbox isn't installed or fails to load.
- **LLM (conversation)** — the multi-turn brain runs on the Claude Agent SDK, authenticated the same way the `claude` CLI always was: its own Max-plan OAuth session, no API key needed. Background one-off tasks (e.g. draft-writing jobs) go through a separate, simpler router that auto-detects a local Ollama server, a local LM Studio server, or the `ANTHROPIC_API_KEY` env var before falling back to the `claude` CLI directly.

Optional upgrades: an `ANTHROPIC_API_KEY` for the Anthropic API backend used by background jobs, an `ELEVENLABS_API_KEY` for higher-quality (paid) TTS, the `tts-chatterbox` extra for the default local voice engine (with cloning), or `tts-kokoro` for offline neural TTS.

## Build the Windows executable

```powershell
pip install -e ".[core,build]"
pyinstaller voice.spec
```

`voice.spec` bundles the app as a windowed (no console) single executable. Model files (Whisper weights) are not bundled — they download to the user's cache on first run, keeping the installer small. See the comments in `voice.spec` for PyInstaller-specific gotchas.

## License

MIT — see [LICENSE](LICENSE).
