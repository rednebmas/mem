"""LLM client — supports Ollama (local) and Claude CLI backends."""

import json
import subprocess
import sys
import time
import requests

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3:8b"
DEFAULT_CONTEXT_LENGTH = 8192

# Backend: "ollama" or "claude"
_backend = "claude"


def set_backend(backend):
    """Set the LLM backend: 'ollama' or 'claude'."""
    global _backend
    _backend = backend


def generate(prompt, model=None, context_length=None, thinking=False, allowed_tools=None):
    """Generate a completion using the configured backend."""
    if _backend == "claude":
        return _generate_claude(prompt, allowed_tools=allowed_tools)
    return _generate_ollama(prompt, model, context_length, thinking)


def _generate_claude(prompt, allowed_tools=None):
    """Generate via Claude CLI (claude -p)."""
    start = time.time()
    sys.stderr.write("  Calling Claude...")
    sys.stderr.flush()
    cmd = ["claude", "-p", prompt]
    if allowed_tools:
        cmd += ["--allowedTools"] + allowed_tools
    result = subprocess.run(
        cmd,
        capture_output=True, text=True, timeout=600,
    )
    elapsed = time.time() - start
    if result.returncode != 0:
        sys.stderr.write(f" error in {elapsed:.1f}s\n")
        sys.stderr.flush()
        raise RuntimeError(f"Claude CLI error: {result.stderr[:200]}")
    sys.stderr.write(f" done in {elapsed:.1f}s\n")
    sys.stderr.flush()
    return result.stdout


def _generate_ollama(prompt, model=None, context_length=None, thinking=False):
    """Generate a completion from the local Ollama model (streaming)."""
    model = model or DEFAULT_MODEL
    context_length = context_length or DEFAULT_CONTEXT_LENGTH

    if not thinking:
        prompt = "/no_think " + prompt

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {"num_ctx": context_length},
    }

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            stream=True,
            timeout=(10, 600),
        )
        resp.raise_for_status()
        return _collect_stream(resp, key="response")
    except requests.ConnectionError:
        raise RuntimeError("Ollama not running. Start with: ollama serve")
    except requests.Timeout:
        raise RuntimeError("Ollama connection timed out")
    except requests.HTTPError as e:
        raise RuntimeError(f"Ollama error: {e}")


def chat(messages, model=None, context_length=None, thinking=False):
    """Chat completion with message history (streaming)."""
    model = model or DEFAULT_MODEL
    context_length = context_length or DEFAULT_CONTEXT_LENGTH

    if not thinking and messages:
        messages = list(messages)
        if messages[0]["role"] == "system":
            messages[0] = {**messages[0], "content": "/no_think " + messages[0]["content"]}
        else:
            messages.insert(0, {"role": "system", "content": "/no_think"})

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"num_ctx": context_length},
    }

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json=payload,
            stream=True,
            timeout=(10, 600),
        )
        resp.raise_for_status()
        return _collect_stream_chat(resp)
    except requests.ConnectionError:
        raise RuntimeError("Ollama not running. Start with: ollama serve")
    except requests.Timeout:
        raise RuntimeError("Ollama connection timed out")
    except requests.HTTPError as e:
        raise RuntimeError(f"Ollama error: {e}")


def _collect_stream(resp, key="response"):
    """Collect streaming response chunks into full text, printing progress."""
    parts = []
    token_count = 0
    start = time.time()
    sys.stderr.write("  Generating")
    for line in resp.iter_lines():
        if line:
            chunk = json.loads(line)
            parts.append(chunk.get(key, ""))
            token_count += 1
            if token_count % 50 == 0:
                sys.stderr.write(".")
                sys.stderr.flush()
            if chunk.get("done"):
                break
    elapsed = time.time() - start
    sys.stderr.write(f" {token_count} tokens in {elapsed:.1f}s\n")
    sys.stderr.flush()
    return "".join(parts)


def _collect_stream_chat(resp):
    """Collect streaming chat response chunks, printing progress."""
    parts = []
    token_count = 0
    start = time.time()
    sys.stderr.write("  Generating")
    for line in resp.iter_lines():
        if line:
            chunk = json.loads(line)
            parts.append(chunk.get("message", {}).get("content", ""))
            token_count += 1
            if token_count % 50 == 0:
                sys.stderr.write(".")
                sys.stderr.flush()
            if chunk.get("done"):
                break
    elapsed = time.time() - start
    sys.stderr.write(f" {token_count} tokens in {elapsed:.1f}s\n")
    sys.stderr.flush()
    return "".join(parts)


def is_available():
    """Check if Ollama is running and the default model is available."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        return DEFAULT_MODEL in models or any(DEFAULT_MODEL.split(":")[0] in m for m in models)
    except Exception:
        return False
