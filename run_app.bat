@echo off
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
    set PYTHON_COMMAND=py
) else (
    set PYTHON_COMMAND=python
)

%PYTHON_COMMAND% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Installation failed. Please confirm that Python is installed.
    pause
    exit /b 1
)

%PYTHON_COMMAND% -m streamlit run app.py
pause
