@echo off
setlocal

set "ROOT=%~dp0.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
  "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\src\main.py" %*
) else (
  python "%ROOT%\src\main.py" %*
)

endlocal