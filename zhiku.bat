@echo off
rem Windows entry point: zhiku setup ^| start ^| stop ^| samples ^| check ^| verify ^| test
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\zhiku.ps1" %*
