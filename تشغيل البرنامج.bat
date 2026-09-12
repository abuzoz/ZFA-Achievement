@echo off
rem Launch via the trusted, installed Python so Windows Smart App Control
rem does not block it (a fresh unsigned .exe would be blocked).
cd /d "%~dp0"
start "" pythonw "%~dp0main.py"
if errorlevel 1 (
  start "" py -w "%~dp0main.py"
)
