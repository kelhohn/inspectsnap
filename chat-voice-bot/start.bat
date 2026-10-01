@echo off
chcp 65001 >nul
cd /d "%~dp0"
start "" http://127.0.0.1:8790/
.venv\Scripts\python.exe -m voicebot %*
pause
