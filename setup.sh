#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Setting up mem ==="

# Create venv
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q requests google-auth-oauthlib google-api-python-client

# Make CLI and tools executable
chmod +x bin/mem
chmod +x tools/*

# Symlink mem to /usr/local/bin
if [ -w /usr/local/bin ]; then
    ln -sf "$SCRIPT_DIR/bin/mem" /usr/local/bin/mem
    echo "Linked: /usr/local/bin/mem -> $SCRIPT_DIR/bin/mem"
else
    echo "Note: Run 'sudo ln -sf $SCRIPT_DIR/bin/mem /usr/local/bin/mem' to install globally"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next: mem init ~/mem-personal"
