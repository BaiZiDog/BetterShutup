@echo off
setlocal
cd /d "%~dp0"
python tools\build_exe.py
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" pause
exit /b %EXITCODE%
