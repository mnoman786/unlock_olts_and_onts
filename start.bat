@echo off
title OLT ONT Unlock Tool

:: Activate virtual environment
if not exist env\Scripts\activate.bat (
    echo [ERROR] Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)
call env\Scripts\activate.bat

:: Start server
echo.
echo =====================================================
echo   OLT ONT / ONU Unlock Tool
echo =====================================================
echo.
echo   URL : http://127.0.0.1:8000
echo.
echo   Press Ctrl+C to stop the server.
echo =====================================================
echo.

:: Open browser after 2 seconds
start /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:8000"

python manage.py runserver 127.0.0.1:8000
