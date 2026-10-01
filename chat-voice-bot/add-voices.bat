@echo off
chcp 65001 >nul
cd /d "%~dp0"
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
rem torchcodec несовместим с PyTorch 2.8 и не нужен (WinError 127) - убираем, если пип его поставил
if exist .venv\Lib\site-packages\torchcodec .venv\Scripts\python.exe -m pip uninstall -y -q torchcodec
if not exist voices.csv copy voices.example.csv voices.csv >nul
.venv\Scripts\python.exe add_voices.py %*
pause
