@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Режим проверки без Twitch: печатайте сообщения, Enter - озвучить.
start "" http://127.0.0.1:8790/overlay
.venv\Scripts\python.exe -m voicebot console %*
pause
