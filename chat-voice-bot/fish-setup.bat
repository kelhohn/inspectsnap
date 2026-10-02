@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Сначала запустите setup.bat & pause & exit /b 1)
.venv\Scripts\python.exe -m pip install -q fish-audio-sdk
.venv\Scripts\python.exe configure_fish.py %*
pause
