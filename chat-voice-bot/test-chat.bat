@echo off
chcp 65001 >nul
cd /d "%~dp0"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
rem torchcodec несовместим с PyTorch 2.8 и не нужен (WinError 127) - убираем, если пип его поставил
if exist .venv\Lib\site-packages\torchcodec .venv\Scripts\python.exe -m pip uninstall -y -q torchcodec
if not exist .venv\Scripts\python.exe (echo Сначала запустите setup.bat & pause & exit /b 1)
echo Загружаю нейросеть, 20-60 секунд... Браузер откроется сам, когда бот будет готов.
echo Режим проверки без Twitch: печатайте сообщения, Enter - озвучить. Звук - в колонки.
.venv\Scripts\python.exe -m voicebot console --audio device --open overlay %*
pause
