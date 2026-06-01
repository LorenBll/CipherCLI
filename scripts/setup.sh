#!/bin/bash

# Set up CipherCLI on macOS or Linux.

set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

# Check Python 3.10+.
if ! command -v python3 &>/dev/null; then
  echo "ERROR: Python 3 not found."
  echo "Install Python 3.10+:"
  echo "  macOS: brew install python3"
  echo "  Debian/Ubuntu: sudo apt install python3 python3-venv python3-pip"
  echo "  Fedora: sudo dnf install python3"
  exit 1
fi

PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 10 ]; }; then
  echo "ERROR: Python 3.10+ required; found $PYTHON_VERSION"
  exit 1
fi

echo "Python $PYTHON_VERSION detected."

# Virtual environment.
if [ -d ".venv" ]; then
  read -p "Virtual environment exists. Recreate? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf .venv
  fi
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv || { echo "ERROR: Failed to create virtual environment."; exit 1; }
fi

source .venv/bin/activate

# Install dependencies.
python -m pip install --quiet --upgrade pip
REQ_FILE=".requirements.setup.txt"
trap 'rm -f "$REQ_FILE"' EXIT
grep -vi '^brotli==' requirements.txt > "$REQ_FILE"
python -m pip install --quiet -r "$REQ_FILE" || { echo "ERROR: Failed to install dependencies."; exit 1; }
echo "Dependencies installed."

# Check configuration.
if [ ! -f "resources/configuration.json" ]; then
  echo "WARNING: Create resources/configuration.json before running ServiceHub."
fi

echo ""
echo "CipherCLI setup complete."
echo ""
echo "Next: python src/main.py ck /absolute/path/to/key.key"