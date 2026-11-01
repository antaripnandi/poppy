@echo off
setlocal
if exist "%~dp0venv\Scripts\python.exe" (
    start "" "%~dp0venv\Scripts\python.exe" "%~dp0main.py"
) else if exist "%~dp0.venv\Scripts\python.exe" (
    start "" "%~dp0.venv\Scripts\python.exe" "%~dp0main.py"
) else (
    start "" python "%~dp0main.py"
)
exit /b 0
