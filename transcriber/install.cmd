@echo off
rem Runs install.ps1 (PowerShell's execution policy would block a double-clicked .ps1).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
if "%~1"=="" pause
