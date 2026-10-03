@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
rem Обновляет код бота с GitHub. Ваши config.toml, voices\, voices.csv, models\ и .venv не трогаются.
set "BRANCH=claude/jolly-dijkstra-2pcl5g"
if not "%~1"=="" set "BRANCH=%~1"
set "TMP_DIR=%TEMP%\chat-voice-bot-update"
if exist "%TMP_DIR%" rmdir /s /q "%TMP_DIR%"
mkdir "%TMP_DIR%"
echo Скачиваю ветку %BRANCH% ...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing 'https://github.com/kelhohn/inspectsnap/archive/refs/heads/%BRANCH%.zip' -OutFile '%TMP_DIR%\bot.zip'; Expand-Archive '%TMP_DIR%\bot.zip' '%TMP_DIR%' -Force"
if errorlevel 1 goto fail
set "SRC="
for /d %%D in ("%TMP_DIR%\inspectsnap-*") do set "SRC=%%D\chat-voice-bot"
if not defined SRC goto fail
robocopy "%SRC%" "%CD%" /E /XD .venv voices models out __pycache__ /XF config.toml voices.csv /NFL /NDL /NJH /NJS /NP
if errorlevel 8 goto fail
rmdir /s /q "%TMP_DIR%"
echo.
echo Готово: код обновлён. Запускайте start.bat
pause
exit /b 0
:fail
echo.
echo Не получилось обновить: проверьте интернет и попробуйте ещё раз.
pause
exit /b 1
