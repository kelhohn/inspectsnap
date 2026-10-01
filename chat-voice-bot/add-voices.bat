@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist voices.csv copy voices.example.csv voices.csv >nul
.venv\Scripts\python.exe add_voices.py %*
pause
