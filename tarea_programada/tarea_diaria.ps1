# =====================================================================
#  TAREA DIARIA DEL CENTINELA  (activar / desactivar / ver estado)
# =====================================================================
#  Para que sirve:
#    Windows puede ejecutar el Centinela solo, todos los dias a una hora.
#    Este archivo crea (o apaga) esa "tarea programada".
#
#  IMPORTANTE: el proyecto NO la crea por su cuenta. Si nunca la activas,
#  el Centinela solo corre cuando TU lo ejecutas a mano.
#
#  Lo mas facil: haz doble clic en uno de estos archivos (misma carpeta):
#     activar_tarea_diaria.bat      -> crea/enciende la tarea diaria
#     desactivar_tarea_diaria.bat   -> la apaga (se puede volver a encender)
#     estado_tarea_diaria.bat       -> te dice si esta encendida y cuando corre
#
#  Uso avanzado (desde PowerShell, en esta carpeta):
#     .\tarea_diaria.ps1 activar | desactivar | estado | probar | quitar
#       probar = la ejecuta ahora mismo una vez
#       quitar = la borra por completo de Windows
# =====================================================================

param(
    [ValidateSet("activar", "desactivar", "estado", "probar", "quitar")]
    [string]$Opcion = "estado"
)

# ---------------------------------------------------------------------
#  >>> AJUSTES QUE PUEDES CAMBIAR <<<
# ---------------------------------------------------------------------

# A que hora se ejecuta cada dia (formato 24 horas, "HH:MM").
# Ejemplos: "07:00" = 7 de la manana, "18:30" = 6:30 de la tarde.
# Si lo cambias, vuelve a hacer doble clic en "activar_tarea_diaria.bat".
$HoraDeEjecucion = "07:00"

# Nombre con el que aparece en el "Programador de tareas" de Windows.
# Normalmente no hace falta tocarlo.
$NombreTarea = "CentinelaDeDatos_Diario"

# Cuanto tiempo maximo puede tardar una corrida antes de que Windows la corte.
$MinutosMaximos = 30

# ---------------------------------------------------------------------
#  A partir de aqui no hace falta tocar nada
# ---------------------------------------------------------------------

$RaizProyecto = Split-Path -Parent $PSScriptRoot
$Python       = Join-Path $RaizProyecto ".venv\Scripts\python.exe"
$Programa     = Join-Path $RaizProyecto "src\pipeline.py"
$Tarea        = Get-ScheduledTask -TaskName $NombreTarea -ErrorAction SilentlyContinue

function Mostrar-Estado {
    if (-not $Tarea) {
        Write-Host "La tarea diaria NO existe. El Centinela solo corre cuando tu lo ejecutas."
        Write-Host "Para crearla: doble clic en activar_tarea_diaria.bat"
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $NombreTarea
    if ($Tarea.State -eq "Disabled") {
        Write-Host "La tarea existe pero esta DESACTIVADA (no se ejecutara sola)."
        Write-Host "Para encenderla: doble clic en activar_tarea_diaria.bat"
    } else {
        Write-Host "La tarea esta ACTIVADA."
        Write-Host "Proxima ejecucion: $($info.NextRunTime)"
    }
    Write-Host "Ultima ejecucion:  $($info.LastRunTime)  (resultado: $($info.LastTaskResult); 0 = todo bien)"
}

switch ($Opcion) {

    "activar" {
        if (-not (Test-Path $Python)) {
            Write-Host "No encuentro el Python del proyecto en: $Python"
            Write-Host "Primero crea el entorno (ver la seccion 'Como lo uso' del README)."
            exit 1
        }
        $queEjecuta = New-ScheduledTaskAction -Execute $Python -Argument "`"$Programa`"" -WorkingDirectory $RaizProyecto
        $cuando     = New-ScheduledTaskTrigger -Daily -At $HoraDeEjecucion
        # StartWhenAvailable: si el PC estaba apagado a esa hora, corre al encenderse.
        $reglas     = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
                        -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
                        -ExecutionTimeLimit (New-TimeSpan -Minutes $MinutosMaximos)
        # Corre con TU usuario y solo cuando tienes la sesion de Windows iniciada.
        $quien      = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $NombreTarea -Action $queEjecuta -Trigger $cuando `
            -Settings $reglas -Principal $quien -Force | Out-Null
        $Tarea = Get-ScheduledTask -TaskName $NombreTarea
        Write-Host "Listo: el Centinela se ejecutara todos los dias a las $HoraDeEjecucion."
        Write-Host "(Solo si el PC esta encendido y con tu sesion iniciada; si estaba apagado, corre al encenderlo.)"
        Mostrar-Estado
    }

    "desactivar" {
        if (-not $Tarea) { Write-Host "No hay ninguna tarea creada; no hay nada que desactivar."; break }
        Disable-ScheduledTask -TaskName $NombreTarea | Out-Null
        Write-Host "Listo: la tarea diaria esta APAGADA. El Centinela ya no correra solo."
        Write-Host "Puedes seguir ejecutandolo a mano cuando quieras."
        Write-Host "Para volver a encenderla: doble clic en activar_tarea_diaria.bat"
    }

    "estado" { Mostrar-Estado }

    "probar" {
        if (-not $Tarea) { Write-Host "Primero activa la tarea (activar_tarea_diaria.bat)."; break }
        Start-ScheduledTask -TaskName $NombreTarea
        Write-Host "Ejecutando ahora. Mira logs\centinela.log (o tu Discord) en unos segundos."
    }

    "quitar" {
        if (-not $Tarea) { Write-Host "No hay ninguna tarea creada."; break }
        Unregister-ScheduledTask -TaskName $NombreTarea -Confirm:$false
        Write-Host "Listo: la tarea fue borrada de Windows por completo."
    }
}
