@echo off
setlocal
cd /d "%~dp0"
start "" pythonw -m better_shutup %*
exit /b 0
