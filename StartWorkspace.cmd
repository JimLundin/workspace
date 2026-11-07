@echo off
rem Start Workspace's programs from this checkout. The environment comes from uv.lock.
setlocal
set "PYTHONHOME="
set "PYTHONPATH="
cd /d "%~dp0"
uv sync --native-tls --locked --no-install-project --python 3.15 --quiet || exit /b 1
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0launch.py" start
