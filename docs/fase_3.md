# Fase 3: Migración a PostgreSQL

> Estado: **completada** (2026-11-01)
> Resumen: el pipeline dejó de escribir Excels y ahora carga los datos limpios en PostgreSQL (`centinela_db`, esquema `raw`), con credenciales seguras, un usuario de mínimos privilegios y validación de montos.

---

## 1. Punto de partida (Fases 1 y 2)

| Componente | Archivo | Qué hace |
|---|---|---|
| Generador | `src/generate_data.py` | Crea 3 Excels sucios (ventas, clientes, productos), 1200 filas, semilla 42 |
| Pipeline | `src/pipeline.py` | Lee `data/raw/*.xlsx`, estandariza columnas, limpia textos, convierte fechas |
| Quality Gate | `validate_quality` | Rechaza un archivo si >5 % de sus fechas no se pueden convertir |
| Logger | `src/logger_config.py` | Escribe en consola y en `logs/centinela.log` |
| Config | `config/config.yaml` | Rutas y parámetros (sin hardcodear nada) |

Salida original: Excels limpios en `data/processed/`.

---

## 2. Qué se construyó en la Fase 3

### 2.1 Base de datos y esquemas
- Base de datos: `centinela_db`.
- Esquema `raw`: tablas cargadas por el pipeline (datos limpios pero sin modelar).
- Esquema `analytics`: reservado para la siguiente capa (tablas listas para consumo).

```powershell
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
& $psql -h localhost -U postgres -c "CREATE DATABASE centinela_db"
& $psql -h localhost -U postgres -d centinela_db -c "CREATE SCHEMA IF NOT EXISTS raw" -c "CREATE SCHEMA IF NOT EXISTS analytics"
```

**Por qué dos esquemas:** separar "lo que acaba de llegar" (`raw`) de "lo que está listo para usar" (`analytics`) es la base de la arquitectura por capas de cualquier almacén de datos. Permite reprocesar `raw` sin romper lo que consumen los reportes.

### 2.2 Gestión de credenciales (config + `.env`)
- `config/config.yaml` (se versiona): host, puerto, nombre de la base, esquemas, umbrales de calidad. **Sin secretos.**
- `.env` (NO se versiona, está en `.gitignore`): usuario y contraseña.
- `.env.example` (se versiona): plantilla vacía para quien clone el repo.
- `python-dotenv` carga el `.env`; `sqlalchemy.engine.URL.create` arma la URL escapando caracteres especiales de la contraseña.

**Decisión crítica:** las credenciales NO van en `config.yaml`. Un secreto en un archivo versionado acaba en GitHub y permanece en el historial aunque se borre después.

### 2.3 Usuario de mínimos privilegios: `centinela_app`

**Objetivo.** El pipeline automatizado no debe correr como `postgres` (superusuario). Si el script tiene un bug, la contraseña se filtra o alguien lo explota, un superusuario puede borrar bases enteras, crear usuarios o leer todo el servidor. `centinela_app` solo puede trabajar dentro de este proyecto: es el **principio de mínimo privilegio**.

| Capacidad | `postgres` (admin) | `centinela_app` |
|---|---|---|
| Superusuario | Sí | **No** |
| Crear bases de datos | Sí | **No** (verificado: "permiso denegado") |
| Crear roles | Sí | **No** |
| Conectarse a `centinela_db` | Sí | Sí |
| Crear/modificar tablas en `raw` y `analytics` | Sí | Sí |

Cómo se hizo:
```sql
CREATE ROLE centinela_app LOGIN PASSWORD '***' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE centinela_db TO centinela_app;
GRANT USAGE, CREATE ON SCHEMA raw TO centinela_app;
GRANT USAGE, CREATE ON SCHEMA analytics TO centinela_app;
ALTER TABLE raw.ventas    OWNER TO centinela_app;
ALTER TABLE raw.clientes  OWNER TO centinela_app;
ALTER TABLE raw.productos OWNER TO centinela_app;
```

> **Por qué el `OWNER TO`:** `to_sql(..., if_exists="replace")` hace `DROP TABLE` + `CREATE TABLE`. En PostgreSQL solo el dueño puede borrar una tabla; si las tablas siguieran siendo de `postgres`, el pipeline fallaría con "debe ser dueño de la tabla".

Organización del `.env` resultante:

| Variable | Usada por | Rol |
|---|---|---|
| `DB_USER` / `DB_PASSWORD` | El pipeline | `centinela_app` |
| `DB_ADMIN_USER` / `DB_ADMIN_PASSWORD` | Tareas manuales de setup | `postgres` |

### 2.4 Carga a PostgreSQL (`src/pipeline.py` + `src/schema.py`)
- `get_engine(db_config)`: crea la conexión SQLAlchemy (driver `psycopg2`).
- `src/schema.py`: define **una sola vez** las tablas (tipos, PK, CHECK). `init_schema()` las crea si no existen (`create_all`, idempotente).
- `save_to_postgres(df, tabla, engine, schema)`: carga dentro de **una transacción**. Si falla, rollback y los datos anteriores quedan intactos. *(En esta fase era `TRUNCATE` + `append`; en la Fase 5 pasó a **upsert** porque llegan archivos nuevos cada día y vaciar la tabla borraría lo anterior. Ver `docs/fase_5.md`, sección 3.)*
- Resultado: `raw.ventas`, `raw.clientes`, `raw.productos` con 1200 filas cada una.

> **Historia:** la primera versión usaba `to_sql(if_exists="replace")`. Funcionaba, pero cada corrida borraba y recreaba la tabla: se perdían las PK, los tipos volvían a ser los inferidos y un fallo a mitad dejaba la tabla vacía. Se reemplazó por el DDL explícito (sección 2.7).

### 2.7 Tipos correctos y claves primarias (DDL explícito)

| Tabla | Columna | Tipo | Restricciones |
|---|---|---|---|
| ventas | id | BIGINT | **PK** |
| ventas | fecha_venta | DATE | |
| ventas | nombre_cliente | TEXT | |
| ventas | monto_venta | **NUMERIC(12,2)** | NOT NULL, `CHECK (>= 0)` |
| clientes | id_cliente | BIGINT | **PK** |
| clientes | nombre_cliente | TEXT | |
| clientes | fecha_alta | DATE | |
| productos | sku | VARCHAR(20) | **PK** |
| productos | descripcion_producto | TEXT | |
| productos | precio_unitario | **NUMERIC(12,2)** | NOT NULL, `CHECK (>= 0)` |
| productos | fecha_ingreso_producto | DATE | |

Por qué:
- **NUMERIC(12,2) para dinero:** exacto en decimales. `double precision` es binario y acumula errores (0.1 + 0.2 ≠ 0.3); en sumas de miles de ventas esos centavos fantasma se notan.
- **DATE en vez de TIMESTAMP:** los datos no tienen hora; guardar `00:00:00` es ruido y confunde en zonas horarias.
- **PK:** impide duplicados a nivel de base de datos, la última línea de defensa si el pipeline falla.
- **CHECK `>= 0`:** segunda línea de defensa de la validación de montos (el pipeline filtra primero; la base garantiza que ningún otro proceso meta negativos).
- Los montos se redondean a 2 decimales antes de cargar (`round(2)`) para evitar ruido de flotantes en la conversión.

Verificación hecha: `INSERT` de monto `-5` → rechazado por `ck_ventas_monto_no_negativo`; `INSERT` de `id=1` repetido → rechazado por `ventas_pkey`; carga con ids duplicados vía `save_to_postgres` → devuelve `False` y la tabla conserva sus 1200 filas.

**Migración desde la versión anterior (una sola vez):**
```powershell
.\.venv\Scripts\python.exe src\pipeline.py --reset-schema
```
`--reset-schema` **borra y recrea** las tablas (destruye sus datos). Aquí es seguro porque se regeneran desde los Excels. En una corrida normal NO se usa.

### 2.5 Validación de montos negativos (`validate_amounts`)

Se aplica después del Quality Gate de fechas, sobre `monto_venta` (ventas) y `precio_unitario` (productos).

Reglas:
1. **Negativo o nulo/no numérico = inválido.** (`to_numeric(errors="coerce")` convierte basura en NaN, y un NaN se trata igual.)
2. **El 0 es válido** (puede ser una venta promocional o un regalo). Si negocio decide lo contrario, se cambia `< 0` por `<= 0`.
3. **Política en dos niveles:**
   - Inválidos **> umbral** (`quality.max_invalid_amount_pct`, 5 %) → se **rechaza el archivo completo**. Un porcentaje alto indica un problema en el origen, no un dato suelto.
   - Inválidos **≤ umbral** → las filas malas se **apartan (cuarentena)**, se registran en el log con sus números de fila de Excel, y el resto se carga.
4. Toda decisión queda en `logs/centinela.log`.

**Por qué no simplemente borrar o corregir los negativos:** un monto negativo puede ser una devolución legítima o un error de captura; el pipeline no puede saberlo. Corregirlo en silencio (ej. `abs()`) falsearía los datos. Lo correcto es apartarlo, avisar y que un humano decida.

Configuración (en `config.yaml`):
```yaml
quality:
  max_invalid_amount_pct: 0.05
```

Tests: `tests/test_validacion_montos.py` (5 tests de montos; con los de claves de la sección 2.5b son 9, todos pasan). Hacen falta porque **los datos generados no contienen ningún negativo**: sin tests, esta validación nunca se habría ejecutado con un caso real.

### 2.5b Validación de claves repetidas (`validate_unique_keys`)

Se aplica después de la validación de montos, sobre la columna que es clave primaria: `id` (ventas), `id_cliente` (clientes) y `sku` (productos).

Reglas (misma filosofía que los montos, para no tener dos formas distintas de pensar):
1. **Clave nula o repetida = inválida.**
2. Inválidas **> umbral** (`quality.max_invalid_key_pct`, 5 %) → se rechaza el archivo completo.
3. Inválidas **≤ umbral** → se conserva la **primera aparición** de cada clave, se apartan las demás y se anotan en el log con su fila de Excel.

**Por qué existe:** la clave primaria de la base de datos ya impide duplicados, pero su respuesta es "falla toda la carga de esa tabla". Con esta validación, un par de filas repetidas en un Excel no tumban las otras 1198.

**Decisión a revisar:** "quedarse con la primera" es una regla simple, no necesariamente la correcta de negocio (podría interesar la más reciente). Se eligió por simplicidad y predictibilidad; si negocio pide otra, es un cambio de una línea (`keep="last"`).

Tests: 4 casos nuevos en `tests/test_validacion_montos.py` (ahora 9 en total, todos pasan).

### 2.6 Bug corregido: el log perdía líneas con emoji
`logging.FileHandler` no tenía `encoding`; en Windows usa cp1252, que no soporta emojis, así que **descartaba silenciosamente** las líneas con ✅ 💾 ❌ 💥 🏁. Es decir, los rechazos del Quality Gate no se registraban en el archivo. Corregido con `encoding="utf-8"` en el archivo y `sys.stderr.reconfigure(encoding="utf-8")` en consola.

---

## 3. Cómo replicarlo desde cero

```powershell
# 1. Entorno
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Secretos: copiar la plantilla y rellenar
Copy-Item .env.example .env      # luego editar .env con tus valores reales

# 3. Base de datos y esquemas (requiere PGPASSWORD con la clave de postgres)
$psql = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
& $psql -h localhost -U postgres -c "CREATE DATABASE centinela_db"
& $psql -h localhost -U postgres -d centinela_db -c "CREATE SCHEMA IF NOT EXISTS raw" -c "CREATE SCHEMA IF NOT EXISTS analytics"

# 4. Usuario de aplicación: ejecutar el SQL de la sección 2.3 con tu propia contraseña
#    y poner DB_USER / DB_PASSWORD en .env

# 5. Datos y pipeline
.\.venv\Scripts\python.exe src\generate_data.py
.\.venv\Scripts\python.exe src\pipeline.py

# 6. Tests
.\.venv\Scripts\python.exe -m pytest tests -v
```

> Nota: la primera vez, `to_sql` crea las tablas siendo `centinela_app` el dueño; el `ALTER TABLE ... OWNER` solo es necesario si las tablas ya existían creadas por `postgres`.

### Cómo verificar en DBeaver
1. Conexión a `localhost:5432`, base `centinela_db` (activar *Show all databases* si no aparece).
2. *centinela_db → Schemas → raw → Tables* y F5: `clientes`, `productos`, `ventas`.
3. Pestaña **Data** para ver filas; **Properties → Columns** para ver tipos.
4. SQL de control:
   ```sql
   SELECT count(*) FROM raw.ventas;   -- 1200
   SELECT * FROM raw.ventas LIMIT 10;
   ```

---

## 4. Estado verificado

| Comprobación | Resultado |
|---|---|
| Esquemas `raw` y `analytics` existen | OK |
| 3 tablas en `raw`, 1200 filas c/u | OK |
| Pipeline corre como `centinela_app` | OK |
| `centinela_app` no puede crear bases de datos | OK (permiso denegado) |
| Tests de montos | 5/5 |
| Log registra ✅ 💾 ❌ en el archivo | OK |

Tras la sección 2.7 (tipos y PK) también se verificó: montos como `numeric(12,2)`, 3 claves primarias, 2 CHECK, segunda corrida idempotente (1200 filas, sin duplicar) y rollback ante carga fallida.

---

## 5. Deuda técnica conocida (críticas pendientes)

1. ~~Dinero como `double precision`~~ → **resuelto** (NUMERIC(12,2), sección 2.7).
2. ~~`replace` destruía la tabla en cada corrida~~ → **resuelto** (TRUNCATE + append transaccional). Sigue sin haber historial: cada corrida sobrescribe el contenido. Si se necesita, añadir columna `loaded_at` y `append` sin truncar.
3. ~~Sin claves primarias~~ → **resuelto** (PK + CHECK). ~~Ids repetidos tumbaban la carga~~ → **resuelto** (`validate_unique_keys`, sección 2.5b).
4. **Clasificación por nombre de archivo** (`"ventas" in nombre`): `ventas_2025.xlsx` sobrescribiría `raw.ventas`. Mover el mapeo archivo→tabla a `config.yaml`.
5. **`Pandas4Warning`** en `clean_strings` (`select_dtypes(include=['object'])`): romperá en una versión mayor de pandas.
6. **Sin repositorio git.** Antes del primer commit, verificar con `git status` que `.env` no aparezca.
7. **Contraseña del admin** `postgres` expuesta en una conversación durante el desarrollo: rotarla (`ALTER USER postgres PASSWORD '...'`) y actualizar `.env`.
8. **`data/processed/*.xlsx`** son restos de la versión anterior y ya no los usa el pipeline.

---

## 6. Siguiente paso sugerido
Fase 4: capa `analytics` (tablas/vistas derivadas, p. ej. ventas por cliente y mes), corregir los tipos de dato (deuda 1–3) y las alertas por Webhook cuando el Quality Gate rechace archivos.
