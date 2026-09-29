#!/usr/bin/env bash
# The transcriber, with the environment of this folder (./install.sh first).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "Not installed yet: run ./install.sh first." >&2
    exit 1
fi
export HF_HOME="$ROOT/models/huggingface"

# NVIDIA's libraries from pip (cuBLAS, cuDNN): the loader reads LD_LIBRARY_PATH when the
# process starts, so it is set here, before Python.
nvidia_libs="$(find "$ROOT/.venv/lib" -type d -path "*/site-packages/nvidia/*/lib" 2>/dev/null | sort | paste -sd: - || true)"
if [ -n "$nvidia_libs" ]; then
    export LD_LIBRARY_PATH="$nvidia_libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

exec "$PYTHON" -m sb_transcriber "$@"
