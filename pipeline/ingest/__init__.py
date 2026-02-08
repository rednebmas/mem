"""Ingestion pipeline — class-based collector registry with external plugin support."""

import importlib
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .base import Collector
from .. import config

# Auto-discover built-in Collector subclasses from this package
_BUILTIN_MODULES = [
    "browser", "texts", "calls", "claude_code",
    "calendar_events", "email_threads", "reminders",
]

_registry = {}  # name -> Collector instance


def _discover():
    """Import all built-in modules and register Collector subclasses."""
    if _registry:
        return
    for mod_name in _BUILTIN_MODULES:
        try:
            mod = importlib.import_module(f".{mod_name}", package=__name__)
        except Exception as e:
            print(f"  Warning: could not import {mod_name}: {e}", file=sys.stderr)
            continue
        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (isinstance(obj, type) and issubclass(obj, Collector)
                    and obj is not Collector and hasattr(obj, 'name')):
                instance = obj()
                _registry[instance.name] = instance


def get_collectors():
    """Return {name: Collector} for all discovered built-in collectors."""
    _discover()
    return dict(_registry)


# Ordered list of built-in collector names for output formatting
SOURCE_ORDER = ["browser", "texts", "calls", "claude", "calendar", "email", "reminders"]

# Expose collector names for CLI choices
COLLECTOR_NAMES = list(SOURCE_ORDER)


def _run_external_plugins(plugins_config, since_dt, until_dt):
    """Run user-defined external plugin scripts, capturing stdout as markdown."""
    results = {}
    for plugin in plugins_config:
        name = plugin["name"]
        cmd = os.path.expanduser(plugin.get("command", plugin.get("path", "")))
        try:
            result = subprocess.run(
                [cmd, since_dt.isoformat(), (until_dt or datetime.now()).isoformat()],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode == 0 and result.stdout.strip():
                results[name] = result.stdout.strip()
            elif result.returncode != 0:
                print(f"  Warning: plugin '{name}' exited {result.returncode}: {result.stderr[:200]}")
        except Exception as e:
            print(f"  Warning: plugin '{name}' failed: {e}")
    return results


def collect_all(since_dt, sources=None, until_dt=None):
    """Run all (or specified) collectors + external plugins.

    Returns dict mapping source name to its filtered item list string.
    """
    _discover()
    enabled = config.get_collectors()
    plugins = config.get_plugins()

    results = {}
    for name, collector in _registry.items():
        if sources and name not in sources:
            continue
        if enabled and name not in enabled:
            continue
        if not collector.is_available():
            continue
        output = collector.collect(since_dt, until_dt=until_dt)
        if output:
            results[name] = output

    # Run external plugins
    if plugins and not sources:
        plugin_results = _run_external_plugins(plugins, since_dt, until_dt)
        results.update(plugin_results)

    return results


def format_output(results):
    """Combine all source outputs into a single string."""
    # Built-in sources first (in order), then any extras (plugins)
    ordered_keys = [s for s in SOURCE_ORDER if s in results]
    extra_keys = [k for k in results if k not in SOURCE_ORDER]
    all_keys = ordered_keys + sorted(extra_keys)
    parts = [results[s] for s in all_keys]
    return "\n\n".join(parts)
