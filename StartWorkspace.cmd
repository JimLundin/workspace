@echo off
setlocal
set "PYTHONHOME="
set "PYTHONPATH="
start "" /d "%~dp0" pyw -3.15 "%~dp0workspace.pyw"
