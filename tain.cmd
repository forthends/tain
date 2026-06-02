@echo off
rem Tain launcher (Windows)
setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

where uv >nul 2>&1
if errorlevel 1 (
    echo X uv not found. Install from: >&2
    echo   winget install astral-sh.uv >&2
    echo   or: https://astral.sh/uv/ >&2
    exit /b 127
)

if not exist ".venv\.synced" goto needs_sync
if not exist ".venv" goto needs_sync
goto skip_sync

:needs_sync
echo ^>^> First run or lockfile change, syncing deps (~30s)...
call uv sync --frozen
if errorlevel 1 exit /b %errorlevel%
echo. > ".venv\.synced"

:skip_sync
if "%~1"=="" goto help
if "%~1"=="help" goto help
if "%~1"=="-h" goto help
if "%~1"=="--help" goto help

set "CMD=%~1"
shift

if "%CMD%"=="run"      goto run
if "%CMD%"=="new"      goto new
if "%CMD%"=="list"     goto list
if "%CMD%"=="state"    goto state
if "%CMD%"=="log"      goto log
if "%CMD%"=="export"   goto do_export
if "%CMD%"=="dialogue" goto dialogue
if "%CMD%"=="webui"    goto webui
if "%CMD%"=="daemon"   goto daemon
if "%CMD%"=="reset"    goto do_reset
goto passthrough

:run
if "%~1"=="" (
    echo missing agent name 1>&2
    exit /b 1
)
uv run python main.py --agent %1
goto :eof

:new
uv run python main.py --create-agent
goto :eof

:list
uv run python main.py --list-agents
goto :eof

:state
uv run python main.py --agent %1 --state
goto :eof

:log
uv run python main.py --agent %1 --log
goto :eof

:do_export
uv run python main.py --agent %1 --export
goto :eof

:dialogue
uv run python main.py --agent %1 --dialogue
goto :eof

:webui
if "%~1"=="" (
    set "PORT=8000"
) else (
    set "PORT=%~1"
)
start "" "http://localhost:%PORT%"
uv run python main.py --webui --port %PORT%
goto :eof

:daemon
if "%~1"=="" (
    echo Usage: tain daemon ^<start^|stop^|status^> [name] 1>&2
    exit /b 1
)
set "OP=%~1"
if "%OP%"=="start" (
    if "%~2"=="" (
        echo missing agent name 1>&2
        exit /b 1
    )
    uv run python main.py --daemon start --agent %2
) else if "%OP%"=="stop" (
    uv run python main.py --daemon stop
) else if "%OP%"=="status" (
    uv run python main.py --daemon status
) else (
    echo Unknown daemon subcommand: %OP% 1>&2
    exit /b 1
)
goto :eof

:do_reset
rmdir /s /q .venv
echo V reset .venv
goto :eof

:help
echo Tain - Tain Agent Framework launcher
echo.
echo Usage:
echo   tain run ^<name^>           Start a single agent
echo   tain new                  Interactive agent creation wizard
echo   tain list                 List all agents
echo   tain state ^<name^>         Print agent state
echo   tain log ^<name^>           View decision log
echo   tain export ^<name^>        Export agent as standalone package
echo   tain dialogue ^<name^>      REPL dialogue mode
echo   tain webui [port]         Start Web UI ^(default 8000^)
echo   tain daemon ^<op^> [name]   Daemon: op = start^|stop^|status
echo   tain reset                Delete .venv ^(re-sync on next run^)
echo   tain help                 Show this help
echo.
echo Legacy: tain --agent ^<name^> ... passes through to python main.py.
goto :eof

:passthrough
uv run python main.py %CMD% %*
goto :eof
