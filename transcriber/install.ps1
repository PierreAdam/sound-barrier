# Installs the transcriber in this folder, and only here (like a Pinokio app):
#   env\bin       uv (if it is not installed already)
#   env\python    Python itself (managed by uv, not the system's)
#   env\cache     uv's download cache
#   .venv         the libraries: faster-whisper, and NVIDIA's cuBLAS / cuDNN from pip
# Deleting the folder removes everything. Nothing is installed system-wide, the PATH is not
# changed. Only an NVIDIA driver is needed (no CUDA toolkit).
#
# Run it again to update the libraries. Double-click install.cmd, or:
#   powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$env:UV_CACHE_DIR = Join-Path $root "env\cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root "env\python"
$env:UV_LINK_MODE = "copy"

$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) {
    $uv = Join-Path $root "env\bin\uv.exe"
    if (-not (Test-Path $uv)) {
        Write-Host "Installing uv into env\bin (from astral.sh)..."
        $env:UV_INSTALL_DIR = Join-Path $root "env\bin"
        $env:UV_NO_MODIFY_PATH = "1"
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    }
}

$venv = Join-Path $root ".venv"
$python = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "Creating the environment (Python 3.12, kept in env\python)..."
    & $uv venv --python 3.12 --python-preference only-managed $venv
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed" }
}

Write-Host "Installing the libraries (faster-whisper, cuBLAS, cuDNN: about 1.5 GB the first time)..."
& $uv pip install --python $python --upgrade -e "$root[cuda,dev]"
if ($LASTEXITCODE -ne 0) { throw "uv pip install failed" }

Write-Host ""
if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
    Write-Warning "nvidia-smi not found: is the NVIDIA driver installed?"
}
& $python -m sb_transcriber devices

Write-Host ""
Write-Host "Installed. Next, with a token from Sound-Barrier (Settings -> Transcripts):"
Write-Host "  .\transcriber.cmd login https://your-server"
Write-Host "  .\transcriber.cmd list"
Write-Host "  .\transcriber.cmd run --all --gpu all"
