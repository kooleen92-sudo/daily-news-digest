@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not exist logs mkdir logs

if defined DAILYNEWS_PYTHON (
    set "PYTHON_EXE=%DAILYNEWS_PYTHON%"
) else (
    set "PYTHON_EXE=python"
)

echo [%date% %time%] Starting Daily News & Impact Digest Job >> logs\runner.log
"%PYTHON_EXE%" main.py --run-now >> logs\runner.log 2>&1
echo [%date% %time%] Job finished with exit code %errorlevel% >> logs\runner.log

endlocal
