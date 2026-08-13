# Vesper

Vesper is a local-first personal voice assistant. It listens via push-to-talk, transcribes speech, routes it through an LLM of your choice, and speaks back — all through a Three.js orb UI in its own native window.

Beyond conversation, Vesper can read your screen on a hotkey, control your PC (launch apps, focus windows, media/volume), manage calendar events, reminders, and deadlines, and run a proactive heartbeat that checks calendar/email/deadlines/PRs/job alerts in the background.

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

If `ui_enabled` is set in `voice/config.json`, the orb UI opens automatically in its own native window (pywebview/WebView2), falling back to an Edge/Chrome `--app` subprocess if pywebview isn't available. It's also reachable directly at `http://localhost:7070`. The HUD is a galaxy/atomic motif around the orb — rounded glass panels, a drifting parallax starfield, and orbiting status indicators — with state/usage readouts on the left and a **Modules** button (bottom-right) for chat, notices, finance, calendar, reminders, deadlines, jobs, workspace, apps, profiles, and settings (including live keybind rebinding).

Scroll down (or press →) to dock the orb into the corner and maximize the notices feed into a centered panel; scroll up, press ←, or hit Esc to bring the orb back.

### Remote access (phone, tablet, another PC)

By default the server binds to `127.0.0.1` — reachable only from the same machine. To use the orb from another device, set `"ui_host": "0.0.0.0"` in your config (repo `voice/config.json` for dev, or `%APPDATA%/Vesper/config.json` once installed) and restart Vesper. Then, from the other device, open `http://<this-pc's-address>:7070`.

The recommended way to expose that address is [Tailscale](https://tailscale.com/) — install it on both the PC and phone, join the same tailnet, and use the PC's Tailscale IP or MagicDNS name instead of port-forwarding the router. All state-changing endpoints (settings, calendar writes, chat input) already require the per-process session token embedded in the page URL, so widening the bind address doesn't remove auth — it only extends network reach.

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
