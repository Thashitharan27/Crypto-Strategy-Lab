@echo off
title Update Crypto Strategy Lab

echo ==========================================
echo   Updating Crypto Strategy Lab from GitHub
echo ==========================================
echo.

cd /d "C:\CryptoBots\Crypto Strategy Lab"

if errorlevel 1 (
    echo ERROR: Could not find the project folder.
    pause
    exit /b 1
)

if not exist ".git" (
    echo ERROR: This folder is not a Git repository.
    pause
    exit /b 1
)

echo Checking Git status...
echo.
git status --short

echo.
echo Pulling latest changes from GitHub...
echo.

git pull --ff-only

if errorlevel 1 (
    echo.
    echo ==========================================
    echo UPDATE FAILED
    echo ==========================================
    echo.
    echo This may happen if you have local changes
    echo or the local and GitHub branches conflict.
    echo.
    echo Nothing was forcefully overwritten.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo UPDATE COMPLETED SUCCESSFULLY
echo ==========================================
echo.

pause