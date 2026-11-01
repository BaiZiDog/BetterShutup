@echo off
setlocal
cd /d "%~dp0"
python -m better_shutup %*
if errorlevel 1 pause
