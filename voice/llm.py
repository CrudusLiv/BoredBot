"""LLM backend router for Vesper.

Supports four backends, probed in priority order on auto-detect:
  1. ollama      -- local Ollama server (localhost:11434)
  2. lmstudio    -- local LM Studio server (localhost:1234, OpenAI-compatible)
  3. anthropic   -- Anthropic API via SDK (ANTHROPIC_API_KEY env var)
  4. claude_cli  -- claude -p subprocess (CLAUDE_CODE_OAUTH_TOKEN or API key)

Configure via voice config key llm_backend or %APPDATA%/Vesper/llm-config.json.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path
from threading import Lock, Thread, Timer
from typing import Any, Iterator


# ---- Config helpers -----------------------------------------------------------

def _llm_config() -> dict[str, Any]:
    from voice import config as cfg
    c = cfg.load()
    base: dict[str, Any] = {
        "backend": c.get("llm_backend", "auto"),
        "ollama_url": "http://localhost:11434",
        "ollama_model": c.get("llm_ollama_model", "llama3.2"),
        "lmstudio_url": "http://localhost:1234",
        "lmstudio_model": c.get("llm_lmstudio_model", "local-model"),
        "anthropic_model": c.get("llm_anthropic_model", "claude-sonnet-4-6"),
        "claude_cli_model": c.get("model", "sonnet"),
        "timeout_seconds": 90,
    }
    try:
        p = cfg.get_data_dir() / "llm-config.json"
        if p.exists():
            base.update(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        pass
    return base


# ---- Backend probes -----------------------------------------------------------

def _probe_ollama(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2):
            return True
    except Exception:
        return False


def _probe_lmstudio(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/v1/models", timeout=2):
            return True
    except Exception:
        return False


def _probe_anthropic() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _probe_claude_cli() -> bool:
    try:
        r = subprocess.run(["claude", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ---- Backend implementations --------------------------------------------------

def _record_usage(backend: str, model: str, in_tok: int, out_tok: int,
                  cost_usd: float | None = None) -> None:
    try:
        from voice import usage as _usage
        _usage.record(backend, model, in_tok, out_tok, cost_usd=cost_usd)
    except Exception:
        pass


def _call_ollama(prompt: str, system_prompt: str | None,
                 model: str, url: str, timeout: int) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        **({"system": system_prompt} if system_prompt else {}),
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    _record_usage("ollama", model,
                  data.get("prompt_eval_count", 0), data.get("eval_count", 0))
    return data["response"].strip()


def _call_lmstudio(prompt: str, system_prompt: str | None,
                   model: str, url: str, timeout: int) -> str:
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "model": model, "messages": messages,
        "temperature": 0.7, "max_tokens": 2048,
    }).encode()
    req = urllib.request.Request(
        f"{url}/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    u = data.get("usage") or {}
    _record_usage("lmstudio", model,
                  u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
    return data["choices"][0]["message"]["content"].strip()


def _call_anthropic(prompt: str, system_prompt: str | None,
                    model: str, timeout: int) -> str:
    import anthropic as _anthropic
    client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kwargs: dict[str, Any] = {
        "model": model, "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    msg = client.messages.create(**kwargs)
    _record_usage("anthropic", model,
                  msg.usage.input_tokens, msg.usage.output_tokens)
    return msg.content[0].text.strip()


def _call_claude_cli(prompt: str, system_prompt: str | None,
                     model: str, timeout: int) -> str:
    try:
        from core import llm as _core  # type: ignore
        if hasattr(_core, "call_meta"):
            text, meta = _core.call_meta(prompt, system_prompt=system_prompt,
                                         model=model, timeout=timeout)
            u = meta.get("usage") or {}
            _record_usage("claude_cli", model,
                          u.get("input_tokens", 0), u.get("output_tokens", 0),
                          cost_usd=meta.get("total_cost_usd"))
            return text
        return _core.call(prompt, system_prompt=system_prompt,
                          model=model, timeout=timeout)
    except ImportError:
        pass
    cmd = ["claude", "-p", "--model", model, "--output-format", "json"]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    result = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    out = (result.stdout or "").strip()
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return out
    u = data.get("usage") or {}
    _record_usage("claude_cli", model,
                  u.get("input_tokens", 0), u.get("output_tokens", 0),
                  cost_usd=data.get("total_cost_usd"))
    return (data.get("result") or "").strip()


# ---- Cached active backend ---------------------------------------------------

_active_backend: str | None = None
_lock = Lock()


def detect_backend() -> str:
    """Probe each backend in priority order; return the first available name."""
    conf = _llm_config()
    for name, probe in [
        ("ollama",    lambda: _probe_ollama(conf["ollama_url"])),
        ("lmstudio",  lambda: _probe_lmstudio(conf["lmstudio_url"])),
        ("anthropic", _probe_anthropic),
        ("claude_cli", _probe_claude_cli),
    ]:
        try:
            if probe():
                return name
        except Exception:
            continue
    return "claude_cli"


def _get_backend() -> str:
    global _active_backend
    with _lock:
        if _active_backend is None:
            conf = _llm_config()
            name = conf.get("backend", "auto")
            _active_backend = detect_backend() if name == "auto" else name
        return _active_backend


def reset_backend() -> None:
    """Force re-detection on next call (e.g. after config change)."""
    global _active_backend
    with _lock:
        _active_backend = None


# ---- Public interface --------------------------------------------------------

def call(prompt: str, *, system_prompt: str | None = None,
         model: str = "", timeout: int = 90) -> str:
    """Route a prompt to the active backend and return the response."""
    conf = _llm_config()
    backend = _get_backend()
    timeout = int(conf.get("timeout_seconds", timeout))

    try:
        if backend == "ollama":
            return _call_ollama(
                prompt, system_prompt,
                model or conf["ollama_model"], conf["ollama_url"], timeout,
            )
        if backend == "lmstudio":
            return _call_lmstudio(
                prompt, system_prompt,
                model or conf["lmstudio_model"], conf["lmstudio_url"], timeout,
            )
        if backend == "anthropic":
            return _call_anthropic(
                prompt, system_prompt,
                model or conf["anthropic_model"], timeout,
            )
        return _call_claude_cli(
            prompt, system_prompt,
            model or conf["claude_cli_model"], timeout,
        )
    except Exception as exc:
        print(f"[llm] {backend} error: {exc}", flush=True)
        return ""


def supports_streaming() -> bool:
    """True when the active backend can yield text deltas via stream()."""
    return _get_backend() in ("ollama", "lmstudio", "anthropic")


def stream(prompt: str, *, system_prompt: str | None = None,
           model: str = "", timeout: int = 90):
    """Yield text deltas from the active backend. Raises RuntimeError for
    backends that can't stream — callers must check supports_streaming().
    Mid-stream network errors propagate so callers can fall back to call()."""
    conf = _llm_config()
    backend = _get_backend()
    timeout = int(conf.get("timeout_seconds", timeout))

    if backend == "ollama":
        yield from _stream_ollama(
            prompt, system_prompt,
            model or conf["ollama_model"], conf["ollama_url"], timeout)
    elif backend == "lmstudio":
        yield from _stream_lmstudio(
            prompt, system_prompt,
            model or conf["lmstudio_model"], conf["lmstudio_url"], timeout)
    elif backend == "anthropic":
        yield from _stream_anthropic(
            prompt, system_prompt, model or conf["anthropic_model"], timeout)
    else:
        raise RuntimeError(f"backend {backend!r} does not support streaming")


def _stream_ollama(prompt: str, system_prompt: str | None,
                   model: str, url: str, timeout: int):
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": True,
        **({"system": system_prompt} if system_prompt else {}),
    }).encode()
    req = urllib.request.Request(
        f"{url}/api/generate", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            raw = raw.strip()
            if not raw:
                continue
            chunk = json.loads(raw)
            if chunk.get("response"):
                yield chunk["response"]
            if chunk.get("done"):
                _record_usage("ollama", model,
                              chunk.get("prompt_eval_count", 0),
                              chunk.get("eval_count", 0))
                return


def _stream_lmstudio(prompt: str, system_prompt: str | None,
                     model: str, url: str, timeout: int):
    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = json.dumps({
        "model": model, "messages": messages,
        "temperature": 0.7, "max_tokens": 2048,
        "stream": True,
        "stream_options": {"include_usage": True},
    }).encode()
    req = urllib.request.Request(
        f"{url}/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            body = line[5:].strip()
            if body == "[DONE]":
                return
            try:
                chunk = json.loads(body)
            except json.JSONDecodeError:
                continue
            u = chunk.get("usage")
            if u:
                _record_usage("lmstudio", model,
                              u.get("prompt_tokens", 0),
                              u.get("completion_tokens", 0))
            choices = chunk.get("choices") or []
            if choices:
                delta = (choices[0].get("delta") or {}).get("content")
                if delta:
                    yield delta


def _stream_anthropic(prompt: str, system_prompt: str | None,
                      model: str, timeout: int):
    import anthropic as _anthropic
    client = _anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    kwargs: dict[str, Any] = {
        "model": model, "max_tokens": 2048,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_prompt:
        kwargs["system"] = system_prompt
    with client.messages.stream(**kwargs) as s:
        for text in s.text_stream:
            yield text
        msg = s.get_final_message()
        _record_usage("anthropic", model,
                      msg.usage.input_tokens, msg.usage.output_tokens)


def _mcp_config_json() -> str:
    import sys
    server_path = Path(__file__).parent / "mcp_server.py"
    return json.dumps({
        "mcpServers": {
            "vesper": {"type": "stdio", "command": sys.executable, "args": [str(server_path)]},
        },
    })


def _parse_tool_result_content(content: Any) -> Any:
    """Normalize a tool_result content block's `content` field into a
    plain value. Observed live: a JSON-encoded string wrapping
    {"result": <value>} (FastMCP's auto-wrap for tools that return a bare
    str -- every voice/mcp_server.py tool does). Also tolerates the
    standard Anthropic content-block-list shape (seen from non-MCP tools
    in the same stream, e.g. the CLI's internal ToolSearch), and passes
    anything else through unchanged."""
    if isinstance(content, str):
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return content
        if isinstance(parsed, dict) and "result" in parsed:
            return parsed["result"]
        return parsed
    if isinstance(content, list):
        texts = [b.get("text") for b in content
                 if isinstance(b, dict) and b.get("type") == "text" and b.get("text")]
        if texts:
            return "".join(texts)
        return content
    return content


def stream_mcp(prompt: str, *, system_prompt: str | None = None,
               model: str = "", timeout: int = 90) -> Iterator[dict]:
    """Run one claude -p turn with native MCP tool calling, yielding parsed
    events: {"kind": "text", "text": str}, {"kind": "tool_call", "name":
    str, "input": dict}, {"kind": "tool_result", "name": str, "output":
    Any}, and exactly one final {"kind": "result", "text": str, "usage":
    dict, "cost_usd": float | None}.

    Only tool_use/tool_result pairs for MCP tools (name prefixed
    "mcp__", e.g. "mcp__vesper__search_vault_tool") are surfaced as
    tool_call/tool_result events. This CLI's own deferred-tool-lookup
    machinery (the "ToolSearch" meta-tool, triggered when a global
    settings source is loaded) produces its own tool_use/tool_result
    pair around every not-yet-loaded MCP tool call; that plumbing is
    silently filtered out here rather than surfaced to callers."""
    conf = _llm_config()
    effective_model = model or conf.get("claude_cli_model", "sonnet")
    cmd = [
        "claude", "-p",
        "--setting-sources", "user",
        "--disable-slash-commands",
        "--mcp-config", _mcp_config_json(),
        "--strict-mcp-config",
        "--allowedTools", "mcp__vesper__*",
        "--model", effective_model,
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
    ]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env.setdefault("MCP_TIMEOUT", "60000")  # ms; headroom over confirm_timeout_seconds

    proc = subprocess.Popen(
        cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", env=env,
    )
    # The prompt goes over stdin, not argv (matching _call_claude_cli's
    # input=prompt above) -- Windows' CreateProcess caps the total command
    # line at ~32K chars, and conversation history (accumulated across up
    # to max_history_turns turns) plus the system prompt can exceed that on
    # argv alone. Written from a background thread, not inline, so a
    # prompt bigger than the OS pipe buffer can't deadlock against the
    # stdout read loop below.
    def _feed_stdin() -> None:
        try:
            proc.stdin.write(prompt)
        finally:
            proc.stdin.close()

    stdin_thread = Thread(target=_feed_stdin, daemon=True)
    stdin_thread.start()

    # Watchdog: proc.wait(timeout=...) in the finally block below only runs
    # AFTER the stdout read loop exits, which itself only happens on EOF --
    # so a subprocess that hangs with stdout still open would otherwise
    # block forever with no timeout ever applying. This timer kills the
    # process independently of the read loop if it overruns `timeout`.
    watchdog = Timer(timeout, proc.kill)
    watchdog.daemon = True
    watchdog.start()
    result_seen = False
    pending_tool_names: dict[str, str] = {}
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = event.get("type")
            if etype == "stream_event":
                inner = event.get("event", {})
                if inner.get("type") == "content_block_delta":
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield {"kind": "text", "text": delta["text"]}
            elif etype == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") != "tool_use":
                        continue
                    name = block.get("name", "")
                    if not name.startswith("mcp__"):
                        continue  # CLI plumbing (e.g. ToolSearch), not a Vesper tool call
                    tool_use_id = block.get("id")
                    if tool_use_id:
                        pending_tool_names[tool_use_id] = name
                    yield {"kind": "tool_call", "name": name,
                           "input": block.get("input", {})}
            elif etype == "user":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") != "tool_result":
                        continue
                    tool_use_id = block.get("tool_use_id", "")
                    name = pending_tool_names.pop(tool_use_id, None)
                    if name is None:
                        continue  # not one of our mcp__ tool calls
                    yield {"kind": "tool_result", "name": name,
                           "output": _parse_tool_result_content(block.get("content"))}
            elif etype == "result":
                result_seen = True
                yield {
                    "kind": "result",
                    "text": event.get("result") or "",
                    "usage": event.get("usage") or {},
                    "cost_usd": event.get("total_cost_usd"),
                }
                _record_usage("claude_cli", effective_model,
                              (event.get("usage") or {}).get("input_tokens", 0),
                              (event.get("usage") or {}).get("output_tokens", 0),
                              cost_usd=event.get("total_cost_usd"))
    finally:
        watchdog.cancel()
        stdin_thread.join(timeout=timeout)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        stderr = proc.stderr.read() if proc.stderr else ""
        if proc.returncode != 0:
            print(f"[llm.stream_mcp] exit {proc.returncode}: {stderr[:500]}", flush=True)
        if not result_seen:
            print("[llm.stream_mcp] stream ended with no result event", flush=True)


def get_status() -> dict[str, Any]:
    """Return current backend name, model, and availability for the UI."""
    conf = _llm_config()
    backend = _get_backend()
    model = ""
    available = False
    try:
        if backend == "ollama":
            available = _probe_ollama(conf["ollama_url"])
            model = conf["ollama_model"]
        elif backend == "lmstudio":
            available = _probe_lmstudio(conf["lmstudio_url"])
            model = conf["lmstudio_model"]
        elif backend == "anthropic":
            available = _probe_anthropic()
            model = conf["anthropic_model"]
        else:
            available = _probe_claude_cli()
            model = conf["claude_cli_model"]
    except Exception:
        pass
    return {"backend": backend, "model": model, "available": available}
