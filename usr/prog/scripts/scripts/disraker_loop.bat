@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..\DisRaker") do set "APP_DIR=%%~fI"
for %%I in ("%SCRIPT_DIR%..\config\disraker.json") do set "DEFAULT_CONFIG=%%~fI"
set "LOG_DIR=%APP_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\disraker.log"

if /I "%~1"=="--help" goto :help
if not defined DISRAKER_CONFIG set "DISRAKER_CONFIG=%DEFAULT_CONFIG%"
if not defined DISRAKER_RESTART_DELAY set "DISRAKER_RESTART_DELAY=5"

if not exist "%APP_DIR%\main.py" (
    echo DisRaker was not found at "%APP_DIR%".
    exit /b 2
)

if not exist "%DISRAKER_CONFIG%" (
    if exist "%DEFAULT_CONFIG%.example" (
        copy /Y "%DEFAULT_CONFIG%.example" "%DISRAKER_CONFIG%" >nul
        echo Created "%DISRAKER_CONFIG%".
        echo Edit it and set the Discord token and status_channel_id, then run again.
        exit /b 2
    )
    echo Configuration was not found at "%DISRAKER_CONFIG%".
    exit /b 2
)

if not exist "%APP_DIR%\.venv\Scripts\python.exe" (
    echo Creating the DisRaker Python environment...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%APP_DIR%\.venv"
    ) else (
        python -m venv "%APP_DIR%\.venv"
    )
    if errorlevel 1 (
        echo Failed to create the Python virtual environment.
        exit /b 3
    )
    "%APP_DIR%\.venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 exit /b 3
    "%APP_DIR%\.venv\Scripts\python.exe" -m pip install ^
        -r "%APP_DIR%\requirements.txt"
    if errorlevel 1 exit /b 3
)

set "PYTHON=%APP_DIR%\.venv\Scripts\python.exe"
if defined PYTHONPATH (
    set "PYTHONPATH=%APP_DIR%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%APP_DIR%"
)

if /I "%~1"=="--check" goto :check
if /I "%~1"=="--once" goto :once
if not "%~1"=="" (
    echo Unknown option: %~1
    goto :help_error
)

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
:loop
echo [%date% %time%] Starting DisRaker.>>"%LOG_FILE%"
echo Starting DisRaker. Press Ctrl+C to stop the restart loop.
"%PYTHON%" "%APP_DIR%\main.py"
set "EXIT_CODE=%ERRORLEVEL%"
echo [%date% %time%] DisRaker exited with %EXIT_CODE%.>>"%LOG_FILE%"
echo DisRaker exited with %EXIT_CODE%; restarting in %DISRAKER_RESTART_DELAY% seconds.
timeout /t %DISRAKER_RESTART_DELAY% /nobreak >nul
goto :loop

:once
"%PYTHON%" "%APP_DIR%\main.py"
exit /b %ERRORLEVEL%

:check
"%PYTHON%" -c "import aiohttp, discord; from disraker.config import load_config; c=load_config(); print('DisRaker configuration OK'); print('Printers:', ', '.join(c.printers)); [print(' -', key, value.moonraker.url) for key, value in c.printers.items()]; print('Default status channel:', c.discord.status_channel_id)"
exit /b %ERRORLEVEL%

:help
echo Usage: %~nx0 [--check^|--once^|--help]
echo.
echo   no option  Run forever and restart after failures.
echo   --check    Validate Python dependencies and configuration, then exit.
echo   --once     Run once in the foreground without restarting.
echo   --help     Show this help.
exit /b 0

:help_error
call :help
exit /b 2
