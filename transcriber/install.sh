#!/usr/bin/env bash
# Installs the transcriber in this folder, and only here (like a Pinokio app), on Linux:
#   env/bin       uv (if it is not installed already)
#   env/python    Python itself (managed by uv, not the system's)
#   env/cache     uv's download cache (can be deleted afterwards)
#   .venv         the libraries: faster-whisper, and NVIDIA's cuBLAS / cuDNN from pip
# Deleting the folder removes everything. Nothing is installed system-wide, no shell
# profile is changed. Only an NVIDIA driver is needed (no CUDA toolkit).
#
# Run it again to update the libraries:  ./install.sh   (or: bash install.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export UV_CACHE_DIR="$ROOT/env/cache"
export UV_PYTHON_INSTALL_DIR="$ROOT/env/python"
export UV_LINK_MODE=copy

uv="$(command -v uv || true)"
if [ -z "$uv" ]; then
    uv="$ROOT/env/bin/uv"
    if [ ! -x "$uv" ]; then
        echo "Installing uv into env/bin (from astral.sh)..."
        if command -v curl >/dev/null; then
            download() { curl -LsSf https://astral.sh/uv/install.sh; }
        elif command -v wget >/dev/null; then
            download() { wget -qO- https://astral.sh/uv/install.sh; }
        else
            echo "Neither curl nor wget is installed: install one, or uv itself." >&2
            exit 1
        fi
        download | env UV_INSTALL_DIR="$ROOT/env/bin" UV_NO_MODIFY_PATH=1 sh
    fi
fi

if [ ! -x "$ROOT/.venv/bin/python" ]; then
    echo "Creating the environment (Python 3.12, kept in env/python)..."
    "$uv" venv --python 3.12 --python-preference only-managed "$ROOT/.venv"
fi

echo "Installing the libraries (faster-whisper, cuBLAS, cuDNN: about 1.5 GB the first time)..."
"$uv" pip install --python "$ROOT/.venv/bin/python" --upgrade -e "$ROOT[cuda,dev]"
chmod +x "$ROOT/transcriber.sh"

echo
if ! command -v nvidia-smi >/dev/null; then
    echo "warning: nvidia-smi not found: is the NVIDIA driver installed?" >&2
fi
"$ROOT/transcriber.sh" devices

echo
echo "Installed. Next, with a token from Sound-Barrier (Settings -> Transcripts):"
echo "  ./transcriber.sh login https://your-server"
echo "  ./transcriber.sh list"
echo "  ./transcriber.sh run --all --gpu 0"
