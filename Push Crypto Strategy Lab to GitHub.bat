@echo off
title Push Crypto Strategy Lab to GitHub

echo ==========================================
echo   Push Crypto Strategy Lab to GitHub
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

echo.
echo ==========================================
echo LOCAL CHANGES
echo ==========================================
echo.

git status --short

echo.
echo ==========================================
echo Adding local changes...
echo ==========================================
echo.

git add -A

echo.
echo Creating commit...
echo.

git commit -m "Desktop update"

if errorlevel 1 (
    echo.
    echo No new changes to commit, or commit failed.
    echo Checking repository status...
    echo.
    git status
    echo.
)

echo.
echo ==========================================
echo Pulling any GitHub changes first...
echo ==========================================
echo.

git pull --rebase

if errorlevel 1 (
    echo.
    echo ==========================================
    echo PULL/REBASE FAILED
    echo ==========================================
    echo.
    echo Your local code has NOT been forcefully overwritten.
    echo GitHub push has been stopped.
    echo.
    echo Check the messages above for conflicts.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo Pushing local changes to GitHub...
echo ==========================================
echo.

git push

if errorlevel 1 (
    echo.
    echo ==========================================
    echo PUSH FAILED
    echo ==========================================
    echo.
    echo Your local files are still safe.
    echo Check the error message above.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo PUSH COMPLETED SUCCESSFULLY
echo ==========================================
echo.
echo Your local Crypto Strategy Lab changes
echo have been uploaded to GitHub.
echo.

pause