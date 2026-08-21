from __future__ import annotations
import argparse
import json
import os
import queue
import threading
import time
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
        "voice.stt", "voice.tts", "voice.audio",
        "voice.audit", "voice.heartbeat", "voice.safety", "voice.memory",
        "voice.tray", "voice.ui_server", "voice.tools",
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


def _maybe_start_screen_read(conf: dict) -> "threading.Event | None":
    """Starts the screen-read overlay + hotkey thread if enabled. Returns
    the stop_event to signal on shutdown, or None if the feature is off."""
    if not conf.get("screen_read_enabled", False):
        return None
    from voice import screen_capture, screen_overlay, screen_read, screen_read_hotkeys

    overlay = screen_overlay.ScreenOverlay()
    overlay.start()
    hotkeys = screen_read_hotkeys.ScreenReadHotkeys(
        overlay, screen_capture.capture_active_monitor, screen_read.ask_about_images,
    )
    stop_event = threading.Event()
    threading.Thread(
        target=hotkeys.run, args=(stop_event,), daemon=True, name="vesper-screen-read",
    ).start()
    print("[screen-read] armed")
    return stop_event


def _conversation_loop(
    brain,
    conf: dict,
    use_voice: bool,
    use_text: bool,
    speak_queue: "queue.Queue[str]",
) -> None:
    """The PTT/text conversation loop -- extracted out of run() so it can be
    driven from a background thread (see run()). Blocks until text-mode EOF
    (pure text mode) or forever (voice-only/hybrid mode); the caller decides
    what "forever" means for process shutdown."""
    from voice import config as cfg

    def _emit(event: dict) -> None:
        try:
            from voice import ui_server as _ui
            _ui.post_event(event)
        except Exception:
            pass

    # Hybrid/text-only: a background thread feeds completed typed lines into
    # a queue so the main loop can poll it alongside the PTT key rather than
    # blocking on input(). Pure voice-only mode never starts this thread, so
    # record_ptt()'s own blocking wait-for-press loop is unaffected below.
    _STDIN_CLOSED = object()
    _text_queue: "queue.Queue[object]" = queue.Queue()
    if use_text:
        def _read_text_input() -> None:
            while True:
                try:
                    line = input("you: ").strip()
                except EOFError:
                    _text_queue.put(_STDIN_CLOSED)
                    return
                if line:
                    _text_queue.put(line)

        threading.Thread(target=_read_text_input, daemon=True, name="vesper-text-input").start()

    while True:
        # Drain and print any proactive messages before prompting —
        # spoken via the proactive speaker thread too when use_voice.
        if use_text:
            while True:
                try:
                    text = speak_queue.get_nowait()
                    print(f"vesper: {text}")
                except queue.Empty:
                    break

        user_text: str | None = None
        input_source: str | None = None

        if use_voice and not use_text:
            # Pure voice mode — unchanged: block on the PTT key.
            from voice import silence
            from voice.audio import record_ptt
            from voice.stt import transcribe
            from voice.tts import stop_speaking

            if silence.is_silenced():
                time.sleep(0.5)
                continue
            _emit({"type": "state", "value": "listening"})
            audio = record_ptt(key=cfg.load().get("ptt_key", "`"), on_press=stop_speaking)
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
            input_source = "voice"

        elif use_text and not use_voice:
            # Pure text mode — unchanged: block on stdin.
            item = _text_queue.get()
            if item is _STDIN_CLOSED:
                break
            user_text = item
            input_source = "text"

        else:
            # Hybrid: poll for a typed line or a PTT press, whichever
            # comes first.
            from voice import silence
            from voice.audio import is_ptt_down, record_while_held
            from voice.stt import transcribe
            from voice.tts import stop_speaking

            while True:
                try:
                    item = _text_queue.get_nowait()
                except queue.Empty:
                    pass
                else:
                    if item is _STDIN_CLOSED:
                        user_text, input_source = None, "eof"
                        break
                    user_text, input_source = item, "text"
                    break

                _ptt_key = cfg.load().get("ptt_key", "`")
                if not silence.is_silenced() and is_ptt_down(_ptt_key):
                    _emit({"type": "state", "value": "listening"})
                    audio = record_while_held(key=_ptt_key, on_press=stop_speaking)
                    if audio is None:
                        _emit({"type": "state", "value": "idle"})
                        continue
                    try:
                        transcript = transcribe(audio)
                    except Exception as _stt_err:
                        print(f"\n[STT error] {_stt_err}")
                        _emit({"type": "state", "value": "idle"})
                        continue
                    if transcript.strip():
                        user_text, input_source = transcript, "voice"
                        break
                    _emit({"type": "state", "value": "idle"})
                    continue

                time.sleep(0.05)

            if input_source == "eof":
                break

        if not user_text or not user_text.strip():
            continue

        _ks_action = _match_killswitch(user_text)
        if _ks_action:
            _msg = _apply_killswitch(_ks_action)
            print(f"vesper: {_msg}")
            if input_source == "voice" and not cfg.is_quiet_hours():
                from voice.tts import speak
                speak(_msg, force=True)
            continue

        print("vesper: ", end="", flush=True)
        utt = None
        try:
            for chunk in brain.turn(user_text, source=input_source):
                print(chunk, end=" ", flush=True)
                if input_source == "voice" and not cfg.is_quiet_hours():
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
        elif input_source == "voice":
            _emit({"type": "state", "value": "idle"})


def run() -> None:
    # stdout/stderr default to the OS ANSI codepage (cp1252 on this machine)
    # whenever they aren't attached to a real console -- e.g. piped through
    # the Task Scheduler launcher's `| ForEach-Object` logger. Notice/email
    # text routinely contains emoji or smart punctuation, so an unguarded
    # print() there crashes the process and, worse, leaves the notice
    # unread -- guaranteeing the exact same crash on every restart.
    import sys
    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Earliest point that can read a persisted API key: llm.get_status() below
    # checks os.environ directly, before Brain (and its own load_env() call)
    # ever runs. Load the data-dir .env here so wizard-persisted keys survive
    # a restart in both dev and frozen builds.
    from voice._env_writer import load_env as _load_data_dir_env
    _load_data_dir_env()

    parser = argparse.ArgumentParser(description="Vesper voice assistant")
    parser.add_argument("--voice",   action="store_true", help="Voice-only mode (push-to-talk, no keyboard input)")
    parser.add_argument("--text",     action="store_true", help="Text-only mode (no voice/push-to-talk)")
    parser.add_argument("--smoke-test", action="store_true", help="Import all modules and exit 0 (CI check, no audio hardware needed)")
    parser.add_argument("--version", action="store_true", help="Print version and exit")
    args = parser.parse_args()
    if args.voice and args.text:
        parser.error("--voice and --text are mutually exclusive")
    # Default (neither flag): both input paths are live at once. `--voice`/
    # `--text` narrow to exactly one.
    use_voice = args.voice or not args.text
    use_text = args.text or not args.voice

    if args.version:
        print(_get_version())
        return

    if args.smoke_test:
        _run_smoke_test()
        return

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
    if use_voice:
        print(f"Hold [{conf.get('ptt_key', '`')}] to speak.", end="")
        print("  Or type below." if use_text else "")
    print()

    # Double-clap barge-in: interrupts TTS mid-reply — a hands-free way to
    # stop speech without needing to hold the PTT key.
    _clap_stop: threading.Event | None = None
    if use_voice and conf.get("clap_enabled", False):
        from voice import clap_detector as _clap

        def _on_clap() -> None:
            from voice.tts import speaking as _spk, stop_speaking as _stop_tts
            if not _spk.is_set():
                return  # only claps during speech count — idle claps ignored
            print("[clap] barge-in — stopping speech", flush=True)
            _stop_tts()

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

    _screen_read_stop = _maybe_start_screen_read(conf)

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
            brain=brain,
        )
        hb.start()

    # Proactive speaker runs whenever voice output is available; text-only
    # mode drains the same queue as printed lines in the loop below instead.
    if use_voice and proactive_tts:
        _start_proactive_speaker(speak_queue, _stop_proactive)

    ui_port = int(conf.get("ui_port", 7070))
    if conf.get("ui_enabled", False):
        from voice import ui_server, tray
        ui_server.start(port=ui_port, host=str(conf.get("ui_host", "127.0.0.1")))
        ui_server.set_brain(brain)
        if hb is not None:
            ui_server.set_heartbeat(hb)
        # os._exit: the main loop blocks on audio, so a SystemExit raised in
        # the tray thread would never reach it. Exit code 0 keeps the
        # start_voice.ps1 watchdog's fast-fail backoff out of the picture.
        tray.start(port=ui_port, on_quit=lambda: os._exit(0))

    def _graceful_shutdown() -> None:
        brain.save()
        brain.close()
        _stop_proactive.set()
        if hb:
            hb.stop()
        if _clap_stop:
            _clap_stop.set()
        if _screen_read_stop:
            _screen_read_stop.set()
        print("\nGoodbye.")

    conv_thread = threading.Thread(
        target=_conversation_loop,
        args=(brain, conf, use_voice, use_text, speak_queue),
        daemon=True,
        name="vesper-conversation",
    )
    conv_thread.start()

    if conf.get("ui_enabled", False):
        import signal

        def _on_sigint(signum, frame) -> None:
            _graceful_shutdown()
            os._exit(0)

        signal.signal(signal.SIGINT, _on_sigint)

        from voice import ui_window
        ui_window.start(ui_port, ui_server.TOKEN)
        # Only reached if the native window failed to activate (WebView2
        # unavailable, _create_window() raised) -- ui_window.start() blocks
        # for the process's lifetime on success. Restore default SIGINT
        # handling so the join() below gets the same graceful
        # KeyboardInterrupt path as the ui_enabled=False branch instead of
        # the hard os._exit() above -- there's no native GUI loop left to
        # unblock in this fallback case.
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        ui_server.open_window()

    try:
        conv_thread.join()
    except KeyboardInterrupt:
        _graceful_shutdown()

if __name__ == "__main__":
    run()
