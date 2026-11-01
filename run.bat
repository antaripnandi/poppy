@echo off
setlocal
set "VENV_PY=C:\Users\banta\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    start "" "%VENV_PY%" "%~dp0main.py"
) else (
    start "" python "%~dp0main.py"
)
exit /b 0

