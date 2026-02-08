"""LLM client — Claude CLI backend."""

import subprocess
import sys
import time


def generate(prompt, allowed_tools=None):
    """Generate a completion via Claude CLI (claude -p)."""
    start = time.time()
    sys.stderr.write("  Calling Claude...")
    sys.stderr.flush()
    cmd = ["claude", "-p", "--chrome", prompt]
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
