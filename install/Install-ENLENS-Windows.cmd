<# : Install ENLENS on Windows - double-click this file
@echo off
rem ENLENS @ENLENS_VERSION@: the one-line install for Windows as a file to double-click (since 0.14.5). It runs the
rem PowerShell part below, which is install.ps1 of the same release, so it does what the install line does: it gets
rem uv, downloads the ENLENS package and checks it, installs it, makes the ENLENS icon and opens ENLENS.
rem Windows may ask first, as for any program from the internet: click "More info", then "Run anyway".
rem To update ENLENS later, quit it and run the newest copy of this file. Your projects stay where they are.
rem
rem How it is made: tools/release.py puts install/install.ps1 below the last line of install/Install-ENLENS-Windows.cmd.
rem cmd runs the lines up to "exit /b" and stops there; PowerShell reads the whole file, in which everything up to the
rem end of the last line is a comment. So no line of this part may hold PowerShell's end of comment, and no rem line
rem a percent sign. Keep it plain ASCII; the release file gets Windows line endings.
setlocal
title Install ENLENS
set "ENLENS_SELF=%~f0"
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "Invoke-Expression ([IO.File]::ReadAllText($env:ENLENS_SELF))"
set "ENLENS_RC=%ERRORLEVEL%"
echo.
echo Press any key to close this window.
pause >nul
exit /b %ENLENS_RC%
: the PowerShell part, install.ps1, starts below this line #>
