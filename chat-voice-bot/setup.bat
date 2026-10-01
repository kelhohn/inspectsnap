@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo === Установка Chat Voice Bot ===

rem --- 1. Python 3.11 ---
set "PYEXE="
for /f "delims=" %%i in ('py -3.11 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
if not defined PYEXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PYEXE (
    echo Python 3.11 не найден, ставлю через winget...
    winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements || goto :fail
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)
if not defined PYEXE (
    echo Не нашёл Python после установки. Закройте окно и запустите setup.bat ещё раз.
    goto :fail
)
echo Python: %PYEXE%

rem --- 2. Окружение и библиотеки ---
if not exist ".venv\Scripts\python.exe" ("%PYEXE%" -m venv .venv || goto :fail)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install --upgrade pip || goto :fail
echo Ставлю PyTorch с CUDA (около 3 ГБ, это надолго)...
"%VPY%" -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu126 || goto :fail
"%VPY%" -m pip install -r requirements-f5.txt -c constraints.txt || goto :fail
rem torchcodec несовместим с PyTorch 2.8 и не нужен (WinError 127)
"%VPY%" -m pip uninstall -y -q torchcodec
rem и блокируем его для всех процессов окружения, даже если pip поставит снова
"%VPY%" -c "import voicebot.compat" || goto :fail
"%VPY%" -c "import torch,sys; ok=torch.cuda.is_available(); print('Видеокарта:', torch.cuda.get_device_name(0) if ok else 'НЕ НАЙДЕНА - обновите драйвер NVIDIA'); sys.exit(0 if ok else 1)" || goto :fail

rem --- 3. Настройки и модель ---
if not exist config.toml copy config.example.toml config.toml >nul
set /p CHANNEL="Ваш канал на Twitch (без #): "
echo Скачиваю русскую модель F5-TTS...
"%VPY%" download_models.py --channel "%CHANNEL%" || goto :fail
if not exist voices.csv copy voices.example.csv voices.csv >nul

echo.
echo === Нарезаю голоса персонажей (Demucs + Whisper, первый раз докачивает модели) ===
"%VPY%" add_voices.py || goto :fail
echo.
echo === Тест: озвучиваю мемные фразы всеми голосами ===
"%VPY%" voice_test.py --engines f5 || goto :fail
start "" out\f5

echo.
echo === Готово! ===
echo Открылась папка out\f5 - послушайте, как звучат персонажи.
echo Добавить своих персонажей: впишите ссылки в voices.csv и запустите add-voices.bat
echo Запуск бота: start.bat. Оверлей для OBS: http://127.0.0.1:8790/overlay
pause
exit /b 0

:fail
echo.
echo *** Ошибка установки - пришлите текст выше в чат с Claude ***
pause
exit /b 1
