@echo off
rem Doble clic para DESACTIVAR la ejecucion diaria (se puede volver a activar)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tarea_diaria.ps1" desactivar
echo.
pause
