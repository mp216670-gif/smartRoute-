@echo off
title Socratis Launcher
echo ==================================================
echo      Socratis - AI Fact Checker Launcher
echo ==================================================
echo.
echo [INFO] Temporarily adding Node.js to PATH for this session...
set "PATH=%PATH%;C:\Program Files\nodejs"

echo Checking for Node.js...
node -v >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is still not found.
    echo Please restart your computer or install Node.js manually.
    pause
    exit
)

echo Node.js found. Starting services...
echo.
echo [1/2] Starting Backend Server...
start "Socratis API Server" cmd /k "cd server && echo Installing server deps... && npm install && echo Starting Server... && npm run dev"

echo [2/2] Starting Frontend Client...
start "Socratis Web Client" cmd /k "cd client && echo Installing client deps... && npm install && echo Starting Client... && npm run dev"

echo.
echo App is launching! Check the opened windows.
echo Frontend will typically run at http://localhost:5173
echo.
pause
