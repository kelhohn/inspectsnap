@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Сначала запустите setup.bat & pause & exit /b 1)
echo Загружаю нейросеть, 20-60 секунд... Браузер откроется сам, когда бот будет готов.
echo Режим проверки без Twitch: печатайте сообщения, Enter - озвучить.
.venv\Scripts\python.exe -m voicebot console --open overlay %*
pause
