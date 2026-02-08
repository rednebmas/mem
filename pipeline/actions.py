"""Action plugin system — detect patterns in the routing LLM call, dispatch to handlers.

Actions piggyback on the single routing LLM call for free detection. Each action
contributes a prompt snippet (what to detect) and an output field (structured flags).
After routing, each action's handler receives its flags and can do whatever it wants:
make its own LLM calls, hit APIs, send notifications, etc.

Built-in actions live in actions/<name>/ with detect.md and output.json.
External actions point to user-provided files via config.
"""

import json
import os
import subprocess
from pathlib import Path

from . import config

# Root of the mem repo (one level up from pipeline/)
_MEM_ROOT = Path(__file__).resolve().parent.parent
_BUILTIN_ACTIONS_DIR = _MEM_ROOT / "actions"

# Registry of built-in action handlers: name -> callable(flags_list)
_BUILTIN_HANDLERS = {}


def _register_builtin(name):
    """Decorator to register a built-in action handler."""
    def decorator(fn):
        _BUILTIN_HANDLERS[name] = fn
        return fn
    return decorator


@_register_builtin("auto-calendar")
def _handle_auto_calendar(flags):
    """Process scheduling flags via calendar_from_texts."""
    from .calendar_from_texts import process_schedule_flags
    return process_schedule_flags(flags)


def load_actions() -> list[dict]:
    """Load enabled actions from config. Returns list of action dicts with:
    - name: action name
    - detect_prompt: text to append to routing prompt
    - output_schema: JSON fields to add to routing output
    - handler: 'builtin' or path to external handler script
    """
    cfg = config.load_config()
    raw_actions = cfg.get("actions", [])
    actions = []

    for entry in raw_actions:
        if isinstance(entry, str):
            # Built-in action by name
            action = _load_builtin(entry)
        elif isinstance(entry, dict):
            name = entry["name"]
            if (_BUILTIN_ACTIONS_DIR / name).is_dir() and "prompt" not in entry:
                # Built-in action referenced by name in dict form
                action = _load_builtin(name)
            else:
                # External action
                action = _load_external(entry)
        else:
            continue

        if action:
            actions.append(action)

    return actions


def _load_builtin(name: str) -> dict | None:
    """Load a built-in action from actions/<name>/."""
    action_dir = _BUILTIN_ACTIONS_DIR / name
    detect_path = action_dir / "detect.md"
    output_path = action_dir / "output.json"

    if not detect_path.exists():
        print(f"  Warning: built-in action '{name}' missing detect.md")
        return None

    detect_prompt = detect_path.read_text().strip()
    output_schema = {}
    if output_path.exists():
        output_schema = json.loads(output_path.read_text())

    return {
        "name": name,
        "detect_prompt": detect_prompt,
        "output_schema": output_schema,
        "handler": "builtin",
    }


def _load_external(entry: dict) -> dict | None:
    """Load an external action from user config."""
    name = entry.get("name", "")
    prompt_path = os.path.expanduser(entry.get("prompt", ""))
    handler_path = os.path.expanduser(entry.get("handler", ""))

    if not prompt_path or not os.path.exists(prompt_path):
        print(f"  Warning: action '{name}' prompt not found at {prompt_path}")
        return None

    detect_prompt = Path(prompt_path).read_text().strip()

    # Output schema is optional — if there's an output.json next to the prompt, use it
    output_schema = {}
    output_path = Path(prompt_path).parent / "output.json"
    if output_path.exists():
        output_schema = json.loads(output_path.read_text())
    elif "output_key" in entry:
        # Simple form: just an output key name with example array
        output_schema = {entry["output_key"]: []}

    return {
        "name": name,
        "detect_prompt": detect_prompt,
        "output_schema": output_schema,
        "handler": handler_path,
    }


def get_action_prompt_additions(actions: list[dict]) -> str:
    """Get the combined prompt text to append to the routing prompt."""
    parts = []
    for action in actions:
        parts.append(action["detect_prompt"])
    return "\n\n".join(parts)


def get_action_output_fields(actions: list[dict]) -> dict:
    """Get the combined output schema fields for all actions."""
    fields = {}
    for action in actions:
        fields.update(action.get("output_schema", {}))
    return fields


def dispatch(actions: list[dict], result: dict):
    """After routing, dispatch each action's flagged data to its handler."""
    for action in actions:
        # Collect all output keys this action owns
        flags = {}
        for key in action.get("output_schema", {}):
            if key in result and result[key]:
                flags[key] = result[key]

        if not flags:
            continue

        name = action["name"]
        handler = action["handler"]

        if handler == "builtin":
            if name in _BUILTIN_HANDLERS:
                # Built-in handlers get the first (usually only) value
                first_key = list(flags.keys())[0]
                _BUILTIN_HANDLERS[name](flags[first_key])
            else:
                print(f"  Warning: no built-in handler for action '{name}'")
        else:
            # External handler — pipe the flags as JSON to stdin
            _run_external_handler(name, handler, flags)


def _run_external_handler(name: str, handler_path: str, flags: dict):
    """Run an external action handler, passing flags as JSON on stdin."""
    try:
        result = subprocess.run(
            [handler_path],
            input=json.dumps(flags),
            text=True, timeout=300,
            capture_output=True,
        )
        if result.stdout.strip():
            print(f"  [{name}] {result.stdout.strip()}")
        if result.returncode != 0:
            print(f"  Warning: action '{name}' handler exited {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        print(f"  Warning: action '{name}' handler failed: {e}")
