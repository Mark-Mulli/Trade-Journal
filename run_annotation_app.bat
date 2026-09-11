@echo off
cd /d "%~dp0"
if exist .venv\Scripts\pythonw.exe (
  start "" .venv\Scripts\pythonw.exe annotate.py
) else (
  start "" pythonw annotate.py
)
