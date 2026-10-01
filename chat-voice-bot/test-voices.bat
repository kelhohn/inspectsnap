@echo off
chcp 65001 >nul
cd /d "%~dp0"
.venv\Scripts\python.exe voice_test.py --engines f5 %*
start "" out
pause
