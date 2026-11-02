# Fase 4: Capa analytics y alertas

> Estado: **completada** (2026-11-01).
> Resumen: sobre las tablas de `raw` se crearon vistas listas para reportes (`analytics`); al final de cada corrida el pipeline envía una **tarjeta a Discord** (verde si todo salió bien, roja si falló); y se preparó una **ejecución diaria opcional** (por defecto a las 07:00, apagable con doble clic; sección 6).

Requiere haber completado la Fase 3 (`docs/fase_3.md`).

---

## 1. Capa analytics

### 1.1 Qué es y por qué
- `raw` guarda los datos limpios tal como llegaron. Alguien que quiera un reporte tendría que escribir las sumas y agrupaciones cada vez.
- `analytics` ofrece los resultados ya preparados: "ventas por mes", "ventas por cliente".

### 1.2 Decisión: vistas, no tablas copia
| | Vista | Tabla resumen |
|---|---|---|
| Guarda datos | No (es una consulta guardada) | Sí (una copia) |
| Siempre al día | **Sí, automáticamente** | Hay que recalcularla |
| Complejidad | Mínima | Orquestar refrescos, riesgo de desfase |
| Velocidad con muchísimos datos | Más lenta | Más rápida |

Con 1200 filas, una vista es instantánea y no tiene nada que mantener. **Si algún día hay millones de filas, se convierten en vistas materializadas o tablas.** Hoy sería sobreingeniería.

### 1.3 Vistas creadas (`src/analytics.py`)

**`analytics.ventas_por_mes`**: `mes`, `num_ventas`, `monto_total`, `ticket_promedio`. Excluye ventas sin fecha (son pocas, ≤5 %, y no se pueden ubicar en ningún mes).

**`analytics.ventas_por_cliente`**: `nombre_cliente`, `num_compras`, `monto_total`, `ultima_compra`, ordenada de mayor a menor gasto.

Se crean con `CREATE OR REPLACE VIEW` en cada corrida (idempotente). Se ejecutan con el usuario `centinela_app`, que ya tenía permisos de `CREATE` sobre `analytics`.

### 1.4 Bug evitado: reset del esquema
PostgreSQL **no permite borrar una tabla si hay vistas que dependen de ella**. Como `--reset-schema` borra las tablas de `raw`, ahora primero elimina las vistas (`drop_analytics_views`) y luego las recrea. Sin esto, el reset fallaría.

### 1.5 Verificación hecha
- 12 meses en `ventas_por_mes`.
- `sum(num_ventas)` = 1200 y `sum(monto_total)` = 3 021 026,12, **idéntico** a `sum(monto_venta)` de `raw.ventas`. Prueba de que la vista no pierde ni inventa datos.

### 1.6 Limitación importante (diseño)
`ventas` guarda el **nombre** del cliente, no su `id_cliente`. Por eso:
- `ventas_por_cliente` agrupa por nombre: dos clientes distintos con el mismo nombre se sumarían juntos.
- No se puede hacer un cruce fiable `ventas` ↔ `clientes`. (En los datos de práctica, además, los nombres de ambos archivos se generaron por separado y no coinciden.)

**Solución real:** que el origen de ventas incluya `id_cliente`. Es un problema de los datos de entrada, no del pipeline, y por eso no se maquilló con un cruce por nombre.

---

## 2. Cómo ver las vistas en DBeaver
*centinela_db → Schemas → analytics → Views* (F5). Doble clic → pestaña **Data**. O en SQL:
```sql
SELECT * FROM analytics.ventas_por_mes;
SELECT * FROM analytics.ventas_por_cliente LIMIT 10;
```

---

## 3. Alertas por Discord

### 3.1 Cómo funciona (`src/alerts.py`)
1. Al empezar la corrida se engancha un recolector al logger (`IssueCollector`) que guarda **todo WARNING y ERROR** y cuenta cuántos fueron ERROR.
2. El pipeline lleva la cuenta real de la corrida: archivos cargados, archivos rechazados y filas cargadas.
3. Al terminar (bien o con crash) se envía **una tarjeta (embed)** a Discord:

| Situación | Color | Título | Estado |
|---|---|---|---|
| Todo bien | Verde (`5763719`) | ✅ PIPELINE EJECUTADO CON ÉXITO | Completado |
| Bien, pero se apartaron filas (solo warnings) | Verde | ✅ PIPELINE EJECUTADO CON ÉXITO | Completado con avisos |
| Algún archivo rechazado o carga fallida (ERROR) | Rojo (`15548997`) | ❌ FALLO EN EL PIPELINE | Fallido |
| El pipeline se cae por completo | Rojo | ❌ FALLO EN EL PIPELINE | Fallido |

Campos de la tarjeta: **Estado**, **Archivos procesados** (ej. "3 de 3 cargados"), **Filas cargadas**, **Entorno**, hora de ejecución y pie "Sistema de Monitoreo Automático". El remitente aparece como "Centinela de Datos". La descripción lista las incidencias (máx. 12 líneas).

Por qué un recolector en vez de modificar cada validación: no se tocó ninguna función existente; cualquier warning/error futuro aparece solo en la tarjeta.

**Diferencias deliberadas respecto al ejemplo de diseño recibido:**
- "Archivos procesados" **no es un texto fijo** ("3 Excel"): se calcula. Un valor fijo diría "3" aunque fallaran dos archivos.
- La hora usa **UTC explícito** (`datetime.now(timezone.utc)`). Con `datetime.now().isoformat()` Discord interpreta la hora local como UTC y la muestra desplazada.
- Se usa `urllib` de la librería estándar en vez de `requests`: una dependencia menos.
- Se acepta cualquier código 2xx (Discord responde 204 cuando va bien).

### 3.2 Reglas de seguridad
- **La alerta nunca rompe el pipeline.** Si no hay webhook, o Discord falla, o no hay internet, solo se anota en el log.
- **La URL del webhook es un secreto** (quien la tenga puede escribir en tu canal). Va en `.env` como `DISCORD_WEBHOOK_URL`, nunca en `config.yaml`.
- Sin dependencias nuevas: se usa `urllib` de la librería estándar de Python.
- Se envía un `User-Agent` propio porque Discord bloquea el que trae Python por defecto.

### 3.3 Configuración
`config/config.yaml`:
```yaml
alerts:
  notify_on_success: true            # false = solo avisa cuando hay problemas
  environment: "Local / Desarrollo"  # texto del campo "Entorno"
```
Con `notify_on_success: true` llega una tarjeta **todos los días**. Es útil para saber que el centinela sigue vivo (si un día no llega nada, algo falló en la tarea programada), pero puede cansar. Si molesta, ponlo en `false`.

### 3.4 Cómo activarla
1. En Discord: *Ajustes del canal → Integraciones → Webhooks → Nuevo webhook → Copiar URL*.
2. Pegarla en `.env`:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/....
   ```
3. Ejecutar el pipeline y comprobar que llega la tarjeta verde.

### 3.5 Pruebas realizadas
- **10 tests con red simulada** (`tests/test_alertas.py`): colores y títulos correctos, números reales en los campos, recorte de mensajes largos, `notify_on_success`, pipeline abortado → rojo, sin webhook no falla, fallo de red no rompe el pipeline.
- **Envío real a Discord**: una corrida normal (tarjeta verde) y una corrida con contraseña de base de datos incorrecta a propósito (tarjeta roja por la vía real de "pipeline abortado"). Ambas se enviaron con éxito.

### 3.6 Detalles a conocer
- `--reset-schema` genera un WARNING, así que aparece como "Completado con avisos". Es esperable: es una operación destructiva y conviene que quede registrada.
- **Mensaje de error confuso con contraseña incorrecta:** PostgreSQL responde en español con un acento (`contraseña`) en una codificación que `psycopg2` no logra leer, así que la tarjeta roja dice `'utf-8' codec can't decode byte...` en vez de "autenticación fallida". El aviso rojo llega igual, pero la causa real queda escondida. Para depurar, mira el servidor o prueba la conexión con `psql`.

---

## 4. Cómo replicar esta fase desde cero
Con la Fase 3 funcionando:
```powershell
# 1. Las vistas y las alertas ya forman parte del pipeline: basta ejecutarlo
.\.venv\Scripts\python.exe src\pipeline.py

# 2. (Opcional) activar alertas: poner DISCORD_WEBHOOK_URL en .env

# 3. Tests (19 en total)
.\.venv\Scripts\python.exe -m pytest tests -v

# 4. Programar la ejecución diaria: ver sección 6
```

Archivos nuevos o modificados:
| Archivo | Cambio |
|---|---|
| `src/analytics.py` | **Nuevo.** Define y crea las vistas |
| `src/alerts.py` | **Nuevo.** Recolector de incidencias y envío a Discord |
| `src/pipeline.py` | Crea las vistas tras `init_schema`; `run_pipeline` ahora envuelve a `_run_pipeline` y avisa al final |
| `config/config.yaml` | Sección `alerts` |
| `.env.example` | Variable `DISCORD_WEBHOOK_URL` |
| `tests/test_alertas.py` | **Nuevo.** 10 tests |

---

## 6. Ejecución diaria automática (Programador de tareas de Windows)

> **Es opcional y no se crea sola.** Se activa y desactiva con los dobles clics de la carpeta `tarea_programada/` (ver 6.4). Si nunca la activas, el Centinela solo corre cuando lo ejecutas tú (por ejemplo con `ejecutar_centinela.bat`).

### 6.1 Qué se configura
Al activarla se crea una tarea llamada **`CentinelaDeDatos_Diario`** que ejecuta todos los días a las **07:00** (hora editable en `tarea_programada/tarea_diaria.ps1`):
```
.venv\Scripts\python.exe src\pipeline.py      (carpeta de trabajo: la raíz del proyecto)
```
Se usa el Python del `.venv` con ruta completa, para no depender de qué Python esté en el PATH de quien lance la tarea.

### 6.2 Opciones elegidas y por qué
| Opción | Valor | Por qué |
|---|---|---|
| Ejecutar como | Tu usuario, con sesión iniciada | No requiere guardar tu contraseña de Windows ni permisos de administrador |
| `StartWhenAvailable` | Sí | Si el PC estaba apagado a las 07:00, la tarea se ejecuta en cuanto sea posible |
| Funciona con batería | Sí | Un portátil sin enchufar no debe saltarse la tarea |
| Límite de tiempo | 30 minutos | Si algo se cuelga, no queda un proceso zombi para siempre |
| Si ya hay una corriendo | Ignorar la nueva | Evita dos cargas simultáneas sobre las mismas tablas |

### 6.3 Cómo se crea
Lo hace `tarea_programada/tarea_diaria.ps1` (opción `activar`, con rutas relativas al proyecto). Es equivalente a este código, que se deja como referencia:
```powershell
$root   = 'C:\RUTA\A\Centinela_de_Datos'
$python = "$root\.venv\Scripts\python.exe"
$action   = New-ScheduledTaskAction -Execute $python -Argument "`"$root\src\pipeline.py`"" -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -Daily -At '07:00'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'CentinelaDeDatos_Diario' -Action $action -Trigger $trigger `
  -Settings $settings -Principal $principal -Force
```

### 6.4 Operación diaria
Sin escribir comandos, con doble clic en `tarea_programada/`:

| Archivo | Qué hace |
|---|---|
| `activar_tarea_diaria.bat` | Crea la tarea y la enciende |
| `desactivar_tarea_diaria.bat` | La apaga (se puede reactivar) |
| `estado_tarea_diaria.bat` | Muestra si está encendida, la última ejecución y la próxima |

Para cambiar la hora: edita `$HoraDeEjecucion` en `tarea_diaria.ps1` y vuelve a activar. Las opciones `probar` y `quitar` están en el propio script.

Equivalentes en PowerShell:
```powershell
Start-ScheduledTask -TaskName CentinelaDeDatos_Diario          # ejecutarla ahora mismo
Get-ScheduledTaskInfo -TaskName CentinelaDeDatos_Diario        # LastTaskResult 0 = éxito, próxima ejecución
Disable-ScheduledTask -TaskName CentinelaDeDatos_Diario        # pausarla
Unregister-ScheduledTask -TaskName CentinelaDeDatos_Diario -Confirm:$false   # eliminarla
```
También se puede cambiar la hora desde el Programador de tareas (`taskschd.msc`) → *CentinelaDeDatos_Diario* → *Desencadenadores*.

### 6.5 Verificación hecha
- Se lanzó la tarea manualmente con `Start-ScheduledTask`: terminó con `LastTaskResult = 0`, cargó las 3 tablas y envió la tarjeta a Discord. Es decir, funciona con las rutas, el `.env` y el entorno que usa el Programador, no solo desde la terminal.
- **Primera ejecución programada real (2 nov 2026): no corrió a las 07:00.** El PC se había apagado a la 1:13 a. m. y se encendió hacia las 8:45 a. m. Gracias a `StartWhenAvailable` la tarea arrancó a las 8:48, pero terminó con código `3221225786` (proceso interrumpido) sin escribir nada en el log; la causa exacta no se pudo confirmar. Una ejecución manual posterior terminó bien (código 0). Conclusión: el comando funciona; el fallo fue de entorno (PC apagado y arranque interrumpido).

### 6.6 Límites conocidos (críticas)
- **Solo corre con tu sesión de Windows iniciada.** Si el PC está apagado, o encendido pero sin iniciar sesión, no se ejecuta hasta que inicies sesión. Para correr sin sesión habría que guardar tu contraseña de Windows en la tarea; se descartó por seguridad y por simplicidad.
- **Con el PC apagado a la hora programada, la ejecución se retrasa y puede interrumpirse** (ver 6.5). Si hace falta puntualidad garantizada, conviene un equipo siempre encendido.
- **Necesita PostgreSQL arrancado.** El servicio `postgresql-x64-18` arranca con Windows por defecto; si no, la tarjeta roja avisará.
- **Aparece una ventana de consola unos segundos** al ejecutarse. Es inofensivo.
- ~~**La tarea diaria reprocesaba siempre los mismos Excels** de `data/raw/`.~~ **Resuelto en la Fase 5**: ahora solo se procesa lo que hay en la bandeja `data/inbox/` y cada archivo se mueve a `archive/` o `rejected/` (ver `docs/fase_5.md`). Queda pendiente que alguien o algo deposite los Excels nuevos en esa carpeta.

---

## 5. Deuda técnica y mejoras futuras
1. **Rotar la URL del webhook de Discord:** quedó expuesta en una conversación durante el desarrollo.
2. **`ventas` sin `id_cliente`**: impide cruces fiables (ver 1.6). Hay que corregirlo en el origen.
3. **Clasificación por nombre de archivo** (`"ventas" in nombre`) sigue pendiente: `ventas_2025.xlsx` sobrescribiría `raw.ventas`.
4. **`Pandas4Warning`** en `clean_strings`: romperá en una versión mayor de pandas.
5. **Sin historial de cargas**: cada corrida sobrescribe `raw`. Una columna `loaded_at` o una tabla de auditoría ayudaría.
6. ~~Sin automatización~~ → **resuelto** (sección 6), con los límites descritos allí.
7. **Sin git**: antes del primer commit, comprobar con `git status` que `.env` no aparece.
8. **Rotar la contraseña de `postgres`**, que quedó expuesta durante el desarrollo.
9. **`tests/deteccion_nulls.py`** es un script suelto, no un test.
