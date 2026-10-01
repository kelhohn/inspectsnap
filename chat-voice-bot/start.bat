@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Сначала запустите setup.bat & pause & exit /b 1)
echo Загружаю нейросеть, 20-60 секунд... Браузер откроется сам, когда бот будет готов.
.venv\Scripts\python.exe -m voicebot --open panel %*
pause
