@echo off
rem The transcriber, with the environment of this folder (install.cmd first).
setlocal
set "ROOT=%~dp0"
if not exist "%ROOT%.venv\Scripts\python.exe" (
    echo Not installed yet: run install.cmd first.
    exit /b 1
)
set "HF_HOME=%ROOT%models\huggingface"
set PYTHONUTF8=1
"%ROOT%.venv\Scripts\python.exe" -m sb_transcriber %*
