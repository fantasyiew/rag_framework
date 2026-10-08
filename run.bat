@echo off
rem ============================================================
rem  RAG Framework launcher
rem  Activate .venv and run app (uvicorn, http://127.0.0.1:8000)
rem ============================================================
setlocal

cd /d "%~dp0"

rem Check virtual environment exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] venv not found: .venv\Scripts\python.exe
    echo         Create it with: python -m venv .venv
    echo         Then install:    .venv\Scripts\pip install -e ".[dev]"
    exit /b 1
)

rem Activate virtual environment
call ".venv\Scripts\activate.bat"

rem Run the app
python main.py

endlocal
