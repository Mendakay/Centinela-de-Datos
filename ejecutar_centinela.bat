@echo off
rem =====================================================================
rem  EJECUTAR EL CENTINELA AHORA (doble clic)
rem  Revisa la bandeja data\inbox, carga lo bueno y avisa por Discord.
rem  El detalle de lo ocurrido queda en logs\centinela.log
rem =====================================================================
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No encuentro el entorno de Python del proyecto ^(.venv^).
    echo Revisa la seccion "Como lo uso" del README.
    echo.
    pause
    exit /b 1
)

echo Ejecutando el Centinela de Datos...
echo.
".venv\Scripts\python.exe" src\pipeline.py
set RESULTADO=%errorlevel%

echo.
if %RESULTADO%==0 (
    echo Listo. Mas detalle en logs\centinela.log
) else (
    echo Algo fallo ^(codigo %RESULTADO%^). Revisa logs\centinela.log
)
echo.
pause
