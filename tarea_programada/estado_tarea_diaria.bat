@echo off
rem Doble clic para ver si la ejecucion diaria esta activada
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tarea_diaria.ps1" estado
echo.
pause
