# Fase 5: Bandeja de entrada para Excels nuevos

> Estado: **completada** (2026-11-01).
> Resumen: el pipeline ya no relee siempre los mismos archivos. Mira una carpeta de entrada (`data/inbox/`), procesa solo lo que hay en ella y mueve cada Excel a `archive/` (cargado) o `rejected/` (rechazado). La carga pasó de "vaciar y recargar" a **upsert**, para que los datos nuevos se sumen a los anteriores en lugar de borrarlos.

Requiere las Fases 3 y 4 (`docs/fase_3.md`, `docs/fase_4.md`).

---

## 1. El problema que resuelve
Hasta la Fase 4, la tarea diaria (programada a las 07:00) reprocesaba **los mismos tres Excels** una y otra vez. El centinela cumplía el horario pero no vigilaba nada nuevo. Hacía falta un lugar donde dejar archivos nuevos y una forma de saber cuáles ya se procesaron.

## 2. Cómo funciona

```
data/inbox/      ← aquí se DEJAN los Excels nuevos (único lugar que mira el pipeline)
      │
      ▼  el pipeline los lee, limpia y valida
      ├── pasan los controles y se cargan   →  data/archive/   (con fecha y hora delante)
      ├── los rechaza el guardián           →  data/rejected/  (para que un humano los revise)
      ├── nombre no reconocido              →  data/rejected/
      └── no se pueden leer / falla la BD   →  se QUEDAN en inbox (se reintentan mañana)
```

### 2.1 Cómo se decide a qué tabla va cada Excel
Por una palabra en el **nombre del archivo** (sin importar mayúsculas):

| El nombre contiene | Va a la tabla |
|---|---|
| `ventas` | `raw.ventas` |
| `clientes` | `raw.clientes` |
| `productos` | `raw.productos` |

Ejemplos: `ventas_2025-01.xlsx`, `Ventas_Enero.xlsx` → ventas. `inventario.xlsx` → no reconocido → `rejected/` con un aviso. Las reglas de cada tipo (columnas de fecha, de monto y clave) viven juntas en `TABLE_RULES` (`src/pipeline.py`).

### 2.2 Qué pasa con cada archivo, y por qué

| Situación | Destino | Por qué |
|---|---|---|
| Se carga bien | `archive/` | Ya no hay que procesarlo; se conserva por si hay que auditarlo |
| Rechazado por calidad (fechas, montos, claves) | `rejected/` | Reintentarlo mañana daría el mismo error y una alerta roja **todos los días**. Se aparta para que alguien lo corrija |
| Nombre no reconocido | `rejected/` | El pipeline no sabe dónde guardarlo |
| No se puede leer (corrupto, a medio copiar, abierto en Excel) | Se queda en `inbox/` | Suele ser temporal; se reintenta en la próxima corrida |
| Falla la base de datos | Se queda en `inbox/` | Suele ser temporal (servicio caído); se reintenta |
| `~$algo.xlsx` | Se ignora | Es un archivo temporal que Excel crea mientras un libro está abierto |

Al mover, se antepone la fecha y hora (`20261101_230241_ventas_2024.xlsx`): dos archivos con el mismo nombre en días distintos nunca se pisan. Si no se puede mover (ej. Excel lo tiene abierto), solo se avisa; el archivo se reprocesa mañana y, como la carga es upsert, no pasa nada malo.

---

## 3. Cambio importante: de TRUNCATE a UPSERT

**La Fase 3 hacía `TRUNCATE` + `append`**: vaciar la tabla y cargar el archivo. Eso era correcto con un archivo fijo, pero **con archivos nuevos cada día habría sido desastroso**: cada Excel nuevo habría borrado todo lo cargado antes.

Ahora es un **upsert** (`INSERT ... ON CONFLICT (clave primaria) DO UPDATE`), dentro de una transacción:

| Caso | Resultado |
|---|---|
| La clave no existe en la tabla | La fila se **inserta** |
| La clave ya existe | La fila se **actualiza** con los datos nuevos |
| Las demás filas de la tabla | **No se tocan** |
| Algo falla a mitad | Rollback: la tabla queda como estaba |

Consecuencias buenas: reprocesar un archivo no duplica filas (**idempotente**), y un Excel con una corrección de una venta antigua la actualiza.

Consecuencia a tener en cuenta: **el upsert nunca borra**. Si una venta se elimina en el origen, seguirá en la base de datos. Para este proyecto es lo esperable; borrar requeriría una regla de negocio explícita.

---

## 4. Archivos nuevos o modificados

| Archivo | Cambio |
|---|---|
| `config/config.yaml` | `paths`: `inbox`, `archive`, `rejected` (reemplazan a `raw_data` y `processed_data`) |
| `src/pipeline.py` | `TABLE_RULES`, `detect_table`, `move_file`, `UnreadableFile`, carga por upsert, bucle sobre la bandeja |
| `src/generate_data.py` | Ahora deja los Excels de práctica en `data/inbox/` |
| `src/alerts.py` | Texto de la tarjeta cuando no hay archivos nuevos |
| `tests/test_bandeja_entrada.py` | **Nuevo.** 6 tests |
| `.gitignore` | Ignora el contenido de `inbox/`, `archive/`, `rejected/` |
| `data/inbox/.gitkeep` | Mantiene la carpeta en git aunque esté vacía |

---

## 5. Cómo usarlo

```powershell
# Dejar un Excel nuevo (a mano o copiándolo) en la bandeja:
Copy-Item "C:\ruta\ventas_2025-01.xlsx" data\inbox\

# Ejecutarlo ya: doble clic en ejecutar_centinela.bat, o desde la terminal:
.\.venv\Scripts\python.exe src\pipeline.py
# (Si activaste la ejecución diaria con tarea_programada/, también corre sola a la hora elegida.)

# Para generar datos de práctica en la bandeja:
.\.venv\Scripts\python.exe src\generate_data.py
```

La tarjeta de Discord con la bandeja vacía dice **"Ninguno nuevo"** y es verde: es el comportamiento normal de un día sin datos. Si te cansa, pon `alerts.notify_on_success: false`.

> **Nota sobre "mañana" y "cada día":** en este documento, frases como "se reintenta mañana" o "alerta roja todos los días" suponen que la ejecución diaria (opcional, ver `docs/fase_4.md` sección 6) está activada. Si la usas solo a mano, léelas como "en la próxima corrida".

---

## 6. Verificación hecha (con datos de prueba, luego eliminados)

| Prueba | Resultado |
|---|---|
| Corrida con 3 Excels | 1200 filas por tabla; los 3 archivos pasan a `archive/` con fecha y hora |
| **Segunda corrida con la bandeja vacía** | Log "Bandeja vacía"; la base **conserva** las 1200 filas por tabla |
| Ventas nuevas: 5 ids nuevos + el id 1 corregido | La tabla pasa de 1200 a **1205** filas; el id 1 tiene el monto nuevo y **sigue habiendo una sola fila** con id 1 |
| Ventas con 50 % de montos negativos | Rechazado (alerta roja) y movido a `rejected/` |
| `inventario_2025.xlsx` | Aviso y movido a `rejected/` |
| `clientes_roto.xlsx` (no es un Excel real) | Error registrado; **se queda en `inbox/`** |
| `~$ventas_2025-01.xlsx` | Ignorado |

Después de las pruebas se eliminaron los artefactos, se vaciaron las tablas, se regeneraron los datos de práctica (semilla 42) y se hizo una corrida final limpia: 3 de 3 cargados, 3600 filas.

> **Incidente durante las pruebas:** se pretendía desactivar Discord con `$env:DISCORD_WEBHOOK_URL = ''`, pero en PowerShell eso **borra** la variable y el pipeline la releyó de `.env`. Se enviaron 3 tarjetas de prueba al canal real. Para desactivar de verdad en pruebas, usar una URL inválida, o ejecutar con `notify_on_success: false`.

---

## 7. Límites conocidos (críticas)
1. **Un archivo rechazado a medias no se reintenta solo.** Si el origen corrige un Excel rechazado, hay que mover el archivo corregido de vuelta a `inbox/` (con otro nombre, o el mismo: el prefijo de fecha evita conflictos en `archive`/`rejected`).
2. **Dos archivos del mismo tipo en la misma corrida** se cargan por orden alfabético; si repiten una clave, gana el último. Para ventas con ids únicos no importa.
3. **El tipo se decide por el nombre.** Un nombre como `ventas_y_clientes.xlsx` se clasificaría como ventas (la primera coincidencia). Convención útil: un tipo por archivo, con la palabra clave al principio.
4. **Los Excels deben tener las columnas que el pipeline espera** (ver `COLUMN_MAPPING`). Un Excel con otras columnas pasa la lectura pero puede fallar al cargar: queda en `inbox/` y se reintenta cada día mostrando error. **Resuelto:** `process_file` rechaza el archivo con un mensaje claro si faltan columnas obligatorias y lo aparta a `rejected/`.
5. **Un archivo bloqueado o corrupto** genera una tarjeta roja cada día. **Resuelto en parte:** si lleva más de 24 h en la bandeja se mueve a `rejected/`.
6. **Nadie deposita los Excels automáticamente.** La bandeja resuelve "qué procesar y no repetir", pero alguien (o algo: una carpeta compartida, un correo, un export programado) tiene que dejar los archivos. Eso depende del origen real de los datos.
7. ~~`data/processed/` y `tests/deteccion_nulls.py`~~ (restos de la versión anterior): **eliminados**.
