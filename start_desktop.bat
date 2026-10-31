@echo off
cd /d "%~dp0"
if exist "dist\AtlasPKM.exe" (
  start "" "dist\AtlasPKM.exe"
) else (
  echo dist\AtlasPKM.exe not found. Run build_portable.ps1 first.
  pause
)
