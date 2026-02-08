"""Claude Code conversation history utilities.

Shared between the claude_code collector and the claude_history CLI tool.
"""

import json
import os
from pathlib import Path

CLAUDE_PROJECTS_DIR = Path.home() / '.claude' / 'projects'


def decode_project_path(encoded: str) -> str:
    """Convert encoded project path to readable path."""
    if encoded.startswith('-'):
        return encoded.replace('-', '/', 1).replace('-', '/')
    return encoded


def encode_project_path(path: str) -> str:
    """Convert filesystem path to Claude's encoded format."""
    return path.replace('/', '-')


def get_current_project_encoded() -> str | None:
    """Get encoded project path based on current working directory."""
    cwd = os.getcwd()
    return encode_project_path(cwd)


def extract_content(content) -> str:
    """Extract text from message content (string or array of blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, dict):
                if block.get('type') == 'text':
                    texts.append(block.get('text', ''))
                elif block.get('type') == 'tool_use':
                    texts.append(f"[tool: {block.get('name', 'unknown')}]")
                elif block.get('type') == 'tool_result':
                    texts.append("[tool result]")
        return ' '.join(texts)
    return str(content)
