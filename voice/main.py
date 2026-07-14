from __future__ import annotations
import argparse
import json
import os
import queue
import threading
import time
from pathlib import Path
import voice  # noqa: F401

def _show_notices() -> None:
    from voice import config as cfg
    p = cfg.get_data_dir() / "voice_notices.jsonl"
    if not p.exists():
        return
    raw = [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    entries = [json.loads(l) for l in raw]
    unread = [e for e in entries if not e.get("read")]
    if not unread:
        return
    print(f"\n[{len(unread)} notice(s) while you were away]")
    for n in unread:
        tag = "[!]" if n.get("level") == "URGENT" else "[i]"
        print(f"  {tag} {n['text']}")
    print()
    for e in entries:
        e["read"] = True
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")



def _match_killswitch(text: str) -> str | None:
    """Return 'pause' or 'resume' if text exactly matches a configured
    killswitch voice phrase, else None."""
    from voice import config as cfg
    t = text.strip().lower().rstrip(".,!?")
    for phrase in cfg.load().get("killswitch_voice_phrases", []):
        if t == str(phrase).strip().lower():
            low = str(phrase).lower()
            return "resume" if ("resume" in low or "back" in low) else "pause"
    return None


def _apply_killswitch(action: str) -> str:
    """Pausing makes Vesper fully deaf, so the 'resume' phrase can never be
    heard by voice — resume is the orb's pause button or the tray's Resume item.
    The phrase stays configured because it still works from the text UI."""
    from voice import killswitch
    killswitch.set_paused(action == "pause")
    if action == "pause":
        return "Standing down. Say nothing more — use the tray to bring me back."
    return "Back online."


def _start_proactive_speaker(
    speak_queue: "queue.Queue[str]",
    stop_event: threading.Event,
) -> threading.Thread:
    """Daemon thread: speaks items heartbeat pushes to speak_queue."""
    def _loop() -> None:
        while not stop_event.is_set():
            try:
                text = speak_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                from voice import config as cfg, silence
                if cfg.is_quiet_hours() or silence.is_silenced():
                    continue
                from voice.tts import speak
                speak(text)
            except Exception as _e:
                print(f"[proactive-tts] error: {_e}", flush=True)

    t = threading.Thread(target=_loop, daemon=True, name="vesper-proactive-speaker")
    t.start()
    return t


def _get_version() -> str:
    """Read the installed package version; frozen builds (PyInstaller) can
    lose distribution metadata, so fall back to a dev placeholder instead
    of raising."""
    from importlib.metadata import version, PackageNotFoundError
    try:
        return version("vesper")
    except PackageNotFoundError:
        return "0.0.0-dev"


def _run_smoke_test() -> None:
    """Import every module the frozen build ships; catches missing hidden
    imports (PyInstaller) without needing audio hardware. Exits 0 on success."""
    import importlib
    modules = [
        "voice.config", "voice.migrate", "voice.brain", "voice.llm",
        "voice.stt", "voice.tts", "voice.wakeword", "voice.audio",
        "voice.audit", "voice.heartbeat", "voice.safety", "voice.memory",
        "voice.tray", "voice.ui_server",
        "voice.app_scanner", "voice.approved_apps", "voice.tools",
        "voice.confirm", "voice.killswitch", "voice.silence", "voice.usage",
        "voice.clap_detector",
    ]
    failed = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            failed.append(f"{name}: {exc}")
    if failed:
        print("[smoke-test] FAILED:")
        for line in failed:
            print(f"  {line}")
        raise SystemExit(1)
    print(f"[smoke-test] OK — {len(modules)} modules imported")


def run() -> None:
    # Earliest point that can read a persisted API key: llm.get_status() below
    # checks os.environ directly, before Brain (and its own load_env() call)
    # ever runs. Load the data-dir .env here so wizard-persisted keys survive
    # a restart in both dev and frozen builds.
    from voice._env_writer import load_env as _load_data_dir_env
    _load_data_dir_env()

    parser = argparse.ArgumentParser(description="Vesper voice assistant")
    parser.add_argument("--voice",    action="store_true", help="Push-to-talk voice mode")
    parser.add_argument("--wakeword", action="store_true", help="Always-on wake-word mode (requires openwakeword)")
    parser.add_argument("--smoke-test", action="store_true", help="Import all modules and exit 0 (CI check, no audio hardware needed)")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    args = parser.parse_args()

    if args.version:
        print(_get_version())
        return

    if args.smoke_test:
        _run_smoke_test()
        return

    # Default to wakeword mode when no flag is given
    if not args.voice and not args.wakeword:
        args.wakeword = True
    if args.wakeword:
        args.voice = True  # wakeword implies voice

    from voice.brain import Brain
    from voice import config as cfg, migrate
    migrate.run_if_needed()

    from voice import setup_wizard
    if not setup_wizard.is_setup_complete():
        setup_wizard.run_wizard()

    conf = cfg.load()

    # Single-instance guard: the logon scheduled task keeps Vesper running
    # 24/7, so a manual `py -m voice` would double-run against it (duplicate
    # mic listeners, TTS, heartbeat). The UI port doubles as the instance
    # lock — if something is already listening there, bow out. Exit 0 so the
    # start_voice.ps1 relaunch loop doesn't treat this as a crash.
    if conf.get("ui_enabled"):
        import socket
        _port = int(conf.get("ui_port", 7070))
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as _probe:
            _probe.settimeout(0.5)
            if _probe.connect_ex(("127.0.0.1", _port)) == 0:
                print(f"Vesper already running on port {_port} — exiting.")
                raise SystemExit(0)

    from voice import llm as _llm
    _llm_status = _llm.get_status()
    if _llm_status["available"]:
        print(f"[llm] backend: {_llm_status['backend']}  model: {_llm_status['model']}")
    else:
        print(
            f"[llm] backend: {_llm_status['backend']} — NOT AVAILABLE.\n"
            "  Set ANTHROPIC_API_KEY, run `claude` CLI, or start Ollama/LM Studio."
        )

    brain = Brain()

    _show_notices()
    print("Vesper. Ctrl-C to quit.")
    _ww_engine = conf.get("wakeword_engine", "openwakeword")
    if args.wakeword:
        import importlib.util
        if _ww_engine == "vosk":
            if importlib.util.find_spec("vosk") is None:
                print("vosk not installed — using PTT.  (py -m pip install vosk)")
                args.wakeword = False
            else:
                print(f"Listening for wake word: '{conf.get('wakeword_keyword', 'vesper')}' (vosk).")
        else:
            if importlib.util.find_spec("openwakeword") is None:
                print("openwakeword not installed — using PTT.  (pip install openwakeword)")
                args.wakeword = False
            else:
                _ww_model = conf.get("wakeword_model", "")
                if not _ww_model:
                    print("[wakeword] no model configured — set wakeword_model in config.json")
                else:
                    print(f"Listening for wake word (model: {_ww_model}).")
    if not args.wakeword and args.voice:
        print(f"Hold [{conf.get('ptt_key', 'space')}] to speak.")
    print()

    # Reflects actual playback state from tts._play — wakeword/clap check this
    from voice.tts import speaking as _tts_active

    # Wake-word thread signals this event; main loop blocks on it instead of PTT
    _wakeword_event: threading.Event | None = None
    _wakeword_stop:  threading.Event | None = None
    if args.wakeword:
        _wakeword_event = threading.Event()
        _wakeword_stop  = threading.Event()
        _wakeword_ready = threading.Event()

        def _on_wake():
            _wakeword_event.set()

        from voice import wakeword as _ww
        if _ww_engine == "vosk":
            _ww_kwargs: dict = {
                "callback":    _on_wake,
                "stop_event":  _wakeword_stop,
                "keyword":     conf.get("wakeword_keyword", "vesper"),
                "model_path":  conf.get("wakeword_model", ""),
                "ready_event": _wakeword_ready,
                "mute_event":  _tts_active,
            }
            _ww_target = _ww.listen_vosk
        else:
            _ww_kwargs = {
                "callback":    _on_wake,
                "stop_event":  _wakeword_stop,
                "model_path":  conf.get("wakeword_model", ""),
                "threshold":   float(conf.get("wakeword_threshold", 0.5)),
                "ready_event": _wakeword_ready,
                "mute_event":  _tts_active,
            }
            _ww_target = _ww.listen
        _ww_thread = threading.Thread(
            target=_ww_target, kwargs=_ww_kwargs,
            daemon=True, name="vesper-wakeword",
        )
        _ww_thread.start()

    # Double-clap barge-in: interrupts TTS mid-reply. The wakeword stays muted
    # while Vesper speaks, so the clap is the only interrupt channel there.
    _clap_stop: threading.Event | None = None
    if args.voice and conf.get("clap_enabled", False):
        from voice import clap_detector as _clap

        def _on_clap() -> None:
            from voice.tts import speaking as _spk, stop_speaking as _stop_tts
            if not _spk.is_set():
                return  # only claps during speech count — idle claps ignored
            print("[clap] barge-in — stopping speech", flush=True)
            _stop_tts()
            if _wakeword_event is not None:
                _wakeword_event.set()  # reuse the wake path -> listening turn

        _clap_stop = threading.Event()
        threading.Thread(
            target=_clap.listen,
            kwargs=dict(
                callback=_on_clap,
                stop_event=_clap_stop,
                threshold=float(conf.get("clap_threshold", 0.6)),
                window_s=float(conf.get("clap_window_s", 1.2)),
            ),
            daemon=True, name="vesper-clap",
        ).start()
        print("[clap] double-clap interrupt armed")

    # Proactive TTS: heartbeat pushes spoken text here; proactive speaker thread consumes it
    speak_queue: queue.Queue[str] = queue.Queue()
    proactive_tts = bool(conf.get("proactive_tts", True))
    _stop_proactive = threading.Event()

    hb = None
    if conf.get("heartbeat_enabled", True):
        from voice.heartbeat import Heartbeat
        hb = Heartbeat(
            interval_minutes=int(conf.get("heartbeat_interval_minutes", 30)),
            speak_queue=speak_queue,
            proactive_tts=proactive_tts,
            context_poll_seconds=int(conf.get("context_poll_seconds", 60)),
        )
        hb.start()

    # Proactive speaker runs only in voice mode; text mode drains via loop
    if args.voice and proactive_tts:
        _start_proactive_speaker(speak_queue, _stop_proactive)

    ui_port = int(conf.get("ui_port", 7070))
    if conf.get("ui_enabled", False):
        from voice import ui_server, tray
        ui_server.start(port=ui_port)
        ui_server.set_brain(brain)
        # os._exit: the main loop blocks on audio, so a SystemExit raised in
        # the tray thread would never reach it. Exit code 0 keeps the
        # start_voice.ps1 watchdog's fast-fail backoff out of the picture.
        tray.start(port=ui_port, on_quit=lambda: os._exit(0))

    def _emit(event: dict) -> None:
        try:
            from voice import ui_server as _ui
            _ui.post_event(event)
        except Exception:
            pass

    try:
        while True:
            # Text mode: drain and print any proactive messages before prompting
            if not args.voice:
                while True:
                    try:
                        text = speak_queue.get_nowait()
                        print(f"vesper: {text}")
                    except queue.Empty:
                        break

            if args.voice:
                from voice import silence
                from voice.audio import record_ptt
                from voice.stt import transcribe
                from voice.tts import stop_speaking

                _STOP_WORDS = frozenset({"stop", "cancel", "quiet", "shut up", "nevermind", "never mind", "be quiet"})

                if _wakeword_event is not None:
                    if not _ww_thread.is_alive():
                        print("[wakeword] thread exited — using PTT fallback")
                        _wakeword_event = None
                    else:
                        # Timeout allows recovery if thread dies after is_alive() check
                        if not _wakeword_event.wait(timeout=5.0):
                            continue
                        _wakeword_event.clear()
                        # Silence can engage between detection and here (and the
                        # clap barge-in sets this event directly). Never open the
                        # mic while silenced.
                        if silence.is_silenced():
                            _wakeword_ready.set()
                            continue
                        stop_speaking()
                        print("[wake] triggered — listening …", flush=True)
                        if conf.get("ui_enabled", False):
                            try:
                                from voice import ui_server as _uiw
                                _uiw.ensure_window_open()
                            except Exception:
                                pass
                        _emit({"type": "state", "value": "listening"})
                        from voice.audio import record_vad
                        audio = record_vad()
                        if audio is None:
                            _wakeword_ready.set()
                            _emit({"type": "state", "value": "idle"})
                            continue
                        try:
                            user_text = transcribe(audio)
                        except Exception as _stt_err:
                            print(f"\n[STT error] {_stt_err}")
                            _wakeword_ready.set()
                            _emit({"type": "state", "value": "idle"})
                            continue
                        if not user_text.strip():
                            print("[STT] (nothing transcribed)")
                            _wakeword_ready.set()
                            _emit({"type": "state", "value": "idle"})
                            continue
                        if user_text.strip().lower().rstrip(".,!") in _STOP_WORDS:
                            print("[interrupt] stop command — idle")
                            _wakeword_ready.set()
                            _emit({"type": "state", "value": "idle"})
                            continue
                        _ks_action = _match_killswitch(user_text)
                        if _ks_action:
                            _msg = _apply_killswitch(_ks_action)
                            print(f"vesper: {_msg}")
                            from voice.tts import speak
                            # force: the acknowledgement is the one line that has
                            # to be heard despite the silence it announces.
                            speak(_msg, on_done=_wakeword_ready.set, force=True)
                            _emit({"type": "state", "value": "idle"})
                            continue
                        print(f"[STT] {user_text!r}")
                        # Skip the PTT block below
                        print("vesper: ", end="", flush=True)

                        def _after_speak():
                            _wakeword_ready.set()
                            _emit({"type": "state", "value": "idle"})

                        # Stream sentences straight into the TTS pipeline:
                        # sentence N plays while N+1 synthesizes.
                        utt = None
                        try:
                            for chunk in brain.turn(user_text, source="voice"):
                                print(chunk, end=" ", flush=True)
                                if not cfg.is_quiet_hours():
                                    if utt is None:
                                        from voice.tts import begin_utterance
                                        _emit({"type": "state", "value": "speaking"})
                                        utt = begin_utterance(on_done=_after_speak)
                                    utt.feed(chunk)
                        except Exception as _turn_err:
                            print(f"\n[brain error] {_turn_err}", flush=True)
                            _emit({"type": "state", "value": "error"})
                        print()
                        if utt is not None:
                            utt.close()
                        else:
                            _after_speak()
                        continue

                # PTT path (used when wakeword is off or fell back)
                if silence.is_silenced():
                    time.sleep(0.5)
                    continue
                _emit({"type": "state", "value": "listening"})
                audio = record_ptt(key=conf.get("ptt_key", "space"), on_press=stop_speaking)
                if audio is None:
                    _emit({"type": "state", "value": "idle"})
                    continue
                try:
                    user_text = transcribe(audio)
                except Exception as _stt_err:
                    print(f"\n[STT error] {_stt_err}")
                    _emit({"type": "state", "value": "idle"})
                    continue
                if not user_text.strip():
                    _emit({"type": "state", "value": "idle"})
                    continue
            else:
                try:
                    user_text = input("you: ").strip()
                except EOFError:
                    break
                if not user_text:
                    continue

            _ks_action = _match_killswitch(user_text)
            if _ks_action:
                _msg = _apply_killswitch(_ks_action)
                print(f"vesper: {_msg}")
                if args.voice and not cfg.is_quiet_hours():
                    from voice.tts import speak
                    speak(_msg, force=True)
                continue

            print("vesper: ", end="", flush=True)
            utt = None
            try:
                for chunk in brain.turn(user_text, source="voice" if args.voice else "text"):
                    print(chunk, end=" ", flush=True)
                    if args.voice and not cfg.is_quiet_hours():
                        if utt is None:
                            from voice.tts import begin_utterance
                            _emit({"type": "state", "value": "speaking"})
                            utt = begin_utterance(
                                on_done=lambda: _emit({"type": "state", "value": "idle"}))
                        utt.feed(chunk)
            except Exception as _turn_err:
                print(f"\n[brain error] {_turn_err}", flush=True)
                _emit({"type": "state", "value": "error"})
            print()

            if utt is not None:
                utt.close()
            elif args.voice:
                _emit({"type": "state", "value": "idle"})

    except KeyboardInterrupt:
        brain.save()
        _stop_proactive.set()
        if hb:
            hb.stop()
        if _wakeword_stop:
            _wakeword_stop.set()
        if _clap_stop:
            _clap_stop.set()
        print("\nGoodbye.")

if __name__ == "__main__":
    run()
