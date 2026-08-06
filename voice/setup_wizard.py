"""First-run setup wizard — customtkinter, four pages.

Called from main.py when %APPDATA%\\Vesper\\.setup_complete is absent.
Writes config via voice.config.save() and marks setup complete on finish.
"""
from __future__ import annotations

import threading


def _marker_path():
    from voice import config as cfg
    return cfg.get_data_dir() / ".setup_complete"


def is_setup_complete() -> bool:
    return _marker_path().exists()


def run_wizard() -> None:
    import customtkinter as ctk
    from voice import config as cfg

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = ctk.CTk()
    app.title("Vesper — First-Run Setup")
    app.geometry("560x460")
    app.resizable(False, False)

    state: dict = {}
    pages: list[ctk.CTkFrame] = []
    page_index = {"i": 0}

    container = ctk.CTkFrame(app, fg_color="transparent")
    container.pack(fill="both", expand=True, padx=24, pady=20)

    nav = ctk.CTkFrame(app, fg_color="transparent")
    nav.pack(fill="x", padx=24, pady=(0, 20))

    def show_page(i: int) -> None:
        for p in pages:
            p.pack_forget()
        pages[i].pack(fill="both", expand=True)
        back_btn.configure(state="normal" if i > 0 else "disabled")
        next_btn.configure(text="Finish" if i == len(pages) - 1 else "Next")
        page_index["i"] = i

    def go_next() -> None:
        i = page_index["i"]
        if i == len(pages) - 1:
            _finish()
            return
        show_page(i + 1)

    def go_back() -> None:
        i = page_index["i"]
        if i > 0:
            show_page(i - 1)

    def _finish() -> None:
        updates = {
            "user_name": state.get("user_name_var").get().strip() or "User",
            "timezone_offset_hours": _safe_float(state.get("tz_var").get()),
            "vault_path": state.get("vault_var").get().strip(),
            "llm_backend": state.get("llm_var").get(),
            "tts_engine": state.get("tts_var").get(),
            "tts_voice": state.get("tts_voice_var").get().strip() or "en-GB-SoniaNeural",
        }
        cfg.save(updates)

        import os
        anthropic_key = state.get("anthropic_var").get().strip()
        eleven_key = state.get("eleven_var").get().strip()
        if anthropic_key:
            os.environ["ANTHROPIC_API_KEY"] = anthropic_key
        if eleven_key:
            os.environ["ELEVENLABS_API_KEY"] = eleven_key

        from voice._env_writer import write_env
        write_env({
            "ANTHROPIC_API_KEY": anthropic_key,
            "ELEVENLABS_API_KEY": eleven_key,
        })

        marker = _marker_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("1", encoding="utf-8")
        app.destroy()

    # ── Page 1: Identity ────────────────────────────────────────────────────
    p1 = ctk.CTkFrame(container, fg_color="transparent")
    ctk.CTkLabel(p1, text="Identity", font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 16))
    ctk.CTkLabel(p1, text="What should Vesper call you?").pack(anchor="w")
    user_name_var = ctk.StringVar(value="User")
    ctk.CTkEntry(p1, textvariable=user_name_var, width=300).pack(anchor="w", pady=(6, 18))
    ctk.CTkLabel(p1, text="UTC offset in hours (e.g. -5, 0, 8)").pack(anchor="w")
    tz_var = ctk.StringVar(value="0")
    ctk.CTkEntry(p1, textvariable=tz_var, width=120).pack(anchor="w", pady=6)

    ctk.CTkLabel(p1, text="Obsidian vault folder — optional, enables notes/deadlines/memory").pack(anchor="w", pady=(18, 0))
    vault_var = ctk.StringVar(value="")
    vault_row = ctk.CTkFrame(p1, fg_color="transparent")
    vault_row.pack(anchor="w", pady=6, fill="x")
    ctk.CTkEntry(vault_row, textvariable=vault_var, width=260).pack(side="left")

    def browse_vault() -> None:
        from tkinter import filedialog
        chosen = filedialog.askdirectory(title="Select your Obsidian vault folder")
        if chosen:
            vault_var.set(chosen)

    ctk.CTkButton(vault_row, text="Browse…", command=browse_vault, width=90).pack(side="left", padx=(8, 0))
    state["user_name_var"] = user_name_var
    state["tz_var"] = tz_var
    state["vault_var"] = vault_var
    pages.append(p1)

    # ── Page 2: LLM backend ─────────────────────────────────────────────────
    p2 = ctk.CTkFrame(container, fg_color="transparent")
    ctk.CTkLabel(p2, text="LLM Backend", font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 16))
    llm_var = ctk.StringVar(value="auto")
    ctk.CTkLabel(p2, text="Vesper can run fully local (Ollama/LM Studio) or use an API.").pack(anchor="w")
    llm_status_label = ctk.CTkLabel(p2, text="", text_color="#88cc44")
    llm_status_label.pack(anchor="w", pady=(10, 4))
    llm_menu = ctk.CTkOptionMenu(p2, variable=llm_var, values=["auto", "ollama", "lmstudio", "anthropic", "claude_cli"])
    llm_menu.pack(anchor="w", pady=6)

    def detect() -> None:
        llm_status_label.configure(text="detecting…", text_color="#8888cc")

        def _bg() -> None:
            from voice import llm as _llm
            _llm.reset_backend()
            name = _llm.detect_backend()
            llm_status_label.configure(text=f"detected: {name}", text_color="#88cc44")

        threading.Thread(target=_bg, daemon=True).start()

    ctk.CTkButton(p2, text="Auto-detect", command=detect, width=140).pack(anchor="w", pady=8)
    state["llm_var"] = llm_var
    pages.append(p2)

    # ── Page 3: API keys (optional) ─────────────────────────────────────────
    p3 = ctk.CTkFrame(container, fg_color="transparent")
    ctk.CTkLabel(p3, text="API Keys (optional)", font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 16))
    ctk.CTkLabel(p3, text="Anthropic API key — used if no local LLM is running").pack(anchor="w")
    anthropic_var = ctk.StringVar(value="")
    ctk.CTkEntry(p3, textvariable=anthropic_var, width=380, show="*").pack(anchor="w", pady=(6, 18))
    ctk.CTkLabel(p3, text="ElevenLabs API key — higher quality TTS (costs credits)").pack(anchor="w")
    eleven_var = ctk.StringVar(value="")
    ctk.CTkEntry(p3, textvariable=eleven_var, width=380, show="*").pack(anchor="w", pady=6)
    state["anthropic_var"] = anthropic_var
    state["eleven_var"] = eleven_var
    pages.append(p3)

    # ── Page 4: Voice ────────────────────────────────────────────────────────
    p4 = ctk.CTkFrame(container, fg_color="transparent")
    ctk.CTkLabel(p4, text="Voice", font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 16))
    ctk.CTkLabel(p4, text="TTS engine").pack(anchor="w")
    tts_var = ctk.StringVar(value="edge")
    ctk.CTkOptionMenu(p4, variable=tts_var, values=["edge", "kokoro", "elevenlabs"]).pack(anchor="w", pady=6)
    ctk.CTkLabel(p4, text="TTS voice (edge-tts voice name)").pack(anchor="w", pady=(12, 0))
    tts_voice_var = ctk.StringVar(value="en-GB-SoniaNeural")
    ctk.CTkEntry(p4, textvariable=tts_voice_var, width=300).pack(anchor="w", pady=6)
    state["tts_var"] = tts_var
    state["tts_voice_var"] = tts_voice_var
    pages.append(p4)

    back_btn = ctk.CTkButton(nav, text="Back", command=go_back, width=100, state="disabled")
    back_btn.pack(side="left")
    next_btn = ctk.CTkButton(nav, text="Next", command=go_next, width=100)
    next_btn.pack(side="right")

    show_page(0)
    app.mainloop()


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        return 0.0
