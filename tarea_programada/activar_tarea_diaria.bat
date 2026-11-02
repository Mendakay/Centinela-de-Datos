@echo off
rem Doble clic para ACTIVAR la ejecucion diaria. La hora se cambia en tarea_diaria.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tarea_diaria.ps1" activar
echo.
pause
