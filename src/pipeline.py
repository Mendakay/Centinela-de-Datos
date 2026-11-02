# =====================================================================
#  PIPELINE.PY  -  El "jefe" del Centinela de Datos
# =====================================================================
#  Este archivo revisa la bandeja de entrada (data/inbox), limpia cada Excel,
#  lo revisa, lo guarda en la base de datos y lo mueve a su carpeta.
#
#  GUIA RAPIDA: "Quiero cambiar X, donde lo hago?"
#  ---------------------------------------------------------------------
#  Quiero...                                        Voy a...
#  ---------------------------------------------------------------------
#  Cambiar carpetas, base de datos, % de errores    config/config.yaml
#     tolerado o si avisa cuando todo sale bien
#  Cambiar usuario/clave de la base o el Discord    archivo .env (secreto)
#  Aceptar un tipo nuevo de Excel (ej. "pedidos")   TABLE_RULES (abajo) + src/schema.py
#  Que reconozca otro nombre de columna             COLUMN_MAPPING (abajo)
#  Cambiar que se considera un monto/clave malo     validate_amounts / validate_unique_keys
#  Cambiar el aspecto de la alerta de Discord       src/alerts.py
#  Cambiar los resumenes (ventas por mes, etc.)     src/analytics.py
#  Activar/desactivar la ejecucion diaria           tarea_programada/ (doble clic)
#
#  Para ejecutarlo a mano:   .venv\Scripts\python.exe src\pipeline.py
# =====================================================================

import os
import yaml
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
import sys
import shutil
import time
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import URL
from schema import init_schema, build_tables
from analytics import create_analytics_views, drop_analytics_views
from alerts import IssueCollector, notify_run
from logger_config import setup_logger # Importamos el logger que creamos

logger = setup_logger()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"

load_dotenv(PROJECT_ROOT / ".env")  # Carga DB_USER y DB_PASSWORD

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        return yaml.safe_load(file)

def get_engine(db_config):
    """Crea la conexión a PostgreSQL. URL.create escapa caracteres raros del password."""
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=db_config["host"],
        port=db_config["port"],
        database=db_config["name"],
    )
    return create_engine(url)

class UnreadableFile(Exception):
    """El Excel no se pudo leer (corrupto, abierto por otro programa, copia a medias...)."""

# >>> AQUI SE DEFINE QUE TIPOS DE EXCEL ACEPTA EL CENTINELA <<<
# Cada linea = un tipo de archivo. El tipo se detecta por una palabra en el nombre del Excel
# (ventas_2025-01.xlsx -> "ventas"). Para cada tipo se indica:
#   date_cols   = columnas que son fechas
#   amount_cols = columnas de dinero (no pueden ser negativas ni vacias)
#   key_col     = columna que identifica cada fila (no puede repetirse ni estar vacia)
# Para agregar un tipo nuevo: copia una linea, cambia los nombres, y crea su tabla en src/schema.py.
TABLE_RULES = {
    "ventas":    dict(date_cols=["fecha_venta"], amount_cols=["monto_venta"], key_col="id"),
    "clientes":  dict(date_cols=["fecha_alta"], key_col="id_cliente"),
    "productos": dict(date_cols=["fecha_ingreso_producto"], amount_cols=["precio_unitario"], key_col="sku"),
}

def detect_table(stem):
    """Devuelve a qué tabla corresponde un Excel según su nombre, o None si no se reconoce."""
    stem = stem.lower()
    return next((table for table in TABLE_RULES if table in stem), None)

def move_file(path, dest_dir):
    """Mueve un Excel a otra carpeta anteponiendo la fecha/hora (así nunca se pisa uno anterior).
    Si no se puede mover (ej. está abierto en Excel), solo avisa: se reintentará en la próxima corrida."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{datetime.now():%Y%m%d_%H%M%S}_{path.name}"
    try:
        shutil.move(str(path), str(dest))
        return dest
    except OSError as e:
        logger.warning(f"⚠️ No se pudo mover {path.name} a '{dest_dir.name}': {e}")
        return None

def _upsert_method(pk_cols):
    """Método de to_sql: INSERT ... ON CONFLICT (pk) DO UPDATE. Si la clave ya existe se actualiza la fila."""
    def method(pd_table, conn, keys, data_iter):
        rows = [dict(zip(keys, row)) for row in data_iter]
        if not rows:
            return
        stmt = pg_insert(pd_table.table).values(rows)
        update_cols = {c: stmt.excluded[c] for c in keys if c not in pk_cols}
        if update_cols:
            stmt = stmt.on_conflict_do_update(index_elements=list(pk_cols), set_=update_cols)
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=list(pk_cols))
        conn.execute(stmt)
    return method

def save_to_postgres(df, table_name, engine, schema):
    """Carga el DataFrame con UPSERT en UNA transacción: filas nuevas se insertan, filas cuya clave
    ya existe se actualizan. Reprocesar el mismo archivo no duplica nada y NO borra lo cargado antes.
    Si algo falla (CHECK, tipo inválido...) se hace rollback y los datos anteriores quedan intactos."""
    try:
        df = df.copy()
        for col in ("monto_venta", "precio_unitario"):
            if col in df.columns:
                df[col] = df[col].round(2)  # evita ruido de flotantes antes de NUMERIC(12,2)
        pk_cols = build_tables(schema).tables[f"{schema}.{table_name}"].primary_key.columns.keys()
        with engine.begin() as conn:
            df.to_sql(table_name, conn, schema=schema, if_exists="append", index=False,
                      method=_upsert_method(pk_cols), chunksize=500)
        logger.info(f"💾 {len(df)} filas cargadas (upsert) en {schema}.{table_name}")
        return True
    except Exception as e:
        logger.error(f"💥 Error guardando {schema}.{table_name} (rollback, datos previos intactos): {e}")
        return False

# >>> AQUI SE TRADUCEN LOS NOMBRES DE COLUMNA <<<
# Formato:  "como viene en el Excel": "como se llama en la base de datos".
# Si un Excel trae una columna con otro nombre (ej. "Monto Total"), agrega una linea aqui.
COLUMN_MAPPING = {
    "ID_Cliente": "id_cliente",
    "Nombre Completo": "nombre_cliente",
    "Fecha_Alta": "fecha_alta",
    "cliente": "nombre_cliente",
    "fecha": "fecha_venta",
    "monto": "monto_venta",
    "descripcion": "descripcion_producto",
    "fecha_ingreso": "fecha_ingreso_producto"
}

def clean_strings(df):
    for col in df.select_dtypes(include=['object', 'str']).columns:
        nulos = df[col].isna()  # None/NaN reales: sin esto quedarían como el texto "None"
        df[col] = df[col].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True)
        df.loc[nulos, col] = pd.NA
        df[col] = df[col].replace('nan', pd.NA)
    return df

def standardize_dates(df, date_columns):
    for col in date_columns:
        if col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                # Número de serie de Excel (ej. 45000 = 2023-03-15): sin esto pandas lo lee como 1970
                df[col] = pd.to_datetime(df[col], unit='D', origin='1899-12-30', errors='coerce')
            else:
                df[col] = pd.to_datetime(df[col], format='mixed', dayfirst=True, errors='coerce')
    return df

def validate_quality(df, filename, date_cols, max_null_percentage=0.05):
    """El Guardián: Revisa la calidad antes de guardar.
    (Este 5% de fechas rotas se cambia en el parametro de arriba; los otros limites estan en config/config.yaml)"""
    total_rows = len(df)
    if total_rows == 0:
        logger.error(f"❌ {filename} está vacío. Abortando.")
        return False

    # Validar nulos en columnas clave (fechas)
    for col in date_cols:
        if col in df.columns:
            null_count = df[col].isna().sum()
            null_pct = null_count / total_rows
            
            if null_pct > max_null_percentage:
                logger.error(f"❌ {filename} rechazado: Columna '{col}' tiene {null_pct:.2%} de nulos (Límite: {max_null_percentage:.2%}).")
                return False # El archivo no pasa el control de calidad
                
    logger.info(f"✅ {filename} pasó los controles de calidad.")
    return True # El archivo es apto

def validate_amounts(df, filename, amount_cols, max_invalid_pct=0.05):
    """Valida montos: no negativos y numéricos. Política:
    - Si las filas inválidas superan el umbral -> se rechaza TODO el archivo (devuelve None).
    - Si no, se aparta (cuarentena) solo cada fila inválida, se loguea y se carga el resto.
    El monto 0 se considera válido (puede ser una venta promocional)."""
    total_rows = len(df)
    invalid_mask = pd.Series(False, index=df.index)

    for col in amount_cols:
        if col not in df.columns:
            continue
        n_negative = int((df[col] < 0).sum())
        n_null = int(df[col].isna().sum())
        if n_negative:
            logger.warning(f"⚠️ {filename}: {n_negative} valores NEGATIVOS en '{col}'.")
        if n_null:
            logger.warning(f"⚠️ {filename}: {n_null} valores nulos/no numéricos en '{col}'.")
        invalid_mask |= df[col].isna() | (df[col] < 0)

    n_invalid = int(invalid_mask.sum())
    if n_invalid == 0:
        return df

    invalid_pct = n_invalid / total_rows
    if invalid_pct > max_invalid_pct:
        logger.error(f"❌ {filename} rechazado: {invalid_pct:.2%} de montos inválidos (Límite: {max_invalid_pct:.2%}).")
        return None

    excel_rows = [i + 2 for i in df.index[invalid_mask][:10]]  # +2: cabecera + base 1
    logger.error(f"🧹 {filename}: {n_invalid} filas apartadas por monto inválido. Primeras filas de Excel: {excel_rows}")
    return df[~invalid_mask]

def validate_unique_keys(df, filename, key_col, max_invalid_pct=0.05):
    """Valida la clave primaria: sin nulos y sin repetidos. Misma política que los montos:
    - Si las filas problemáticas superan el umbral -> se rechaza el archivo completo (None).
    - Si no, se conserva la PRIMERA aparición de cada clave y se apartan las demás (se loguean)."""
    if key_col is None or key_col not in df.columns:
        return df

    total_rows = len(df)
    null_mask = df[key_col].isna()
    dup_mask = df[key_col].duplicated(keep="first") & ~null_mask
    invalid_mask = null_mask | dup_mask
    n_invalid = int(invalid_mask.sum())
    if n_invalid == 0:
        return df

    invalid_pct = n_invalid / total_rows
    logger.warning(f"⚠️ {filename}: {int(null_mask.sum())} claves nulas y {int(dup_mask.sum())} repetidas en '{key_col}'.")
    if invalid_pct > max_invalid_pct:
        logger.error(f"❌ {filename} rechazado: {invalid_pct:.2%} de claves inválidas (Límite: {max_invalid_pct:.2%}).")
        return None

    excel_rows = [i + 2 for i in df.index[invalid_mask][:10]]
    logger.error(f"🧹 {filename}: {n_invalid} filas apartadas por clave inválida. Primeras filas de Excel: {excel_rows}")
    return df[~invalid_mask]

def process_file(file_path, date_cols, amount_cols=(), max_invalid_amount_pct=0.05,
                 key_col=None, max_invalid_key_pct=0.05):
    logger.info(f"Procesando: {file_path.name}...")
    
    try:
        df = pd.read_excel(file_path)
        df.columns = df.columns.astype(str).str.strip()  # "fecha " -> "fecha"
        df = df.rename(columns=COLUMN_MAPPING)
        required = [*date_cols, *amount_cols, *([key_col] if key_col else [])]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.error(f"❌ {file_path.name} rechazado: faltan columnas obligatorias {missing}.")
            return None
        df = clean_strings(df)
        df = standardize_dates(df, date_cols)
        
        for col in ['precio_unitario', 'monto_venta']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        # AQUÍ SE APLICA EL GUARDIÁN
        if not validate_quality(df, file_path.name, date_cols):
            return None # Si no pasa, retornamos nada para que no se guarde
        df = validate_amounts(df, file_path.name, amount_cols, max_invalid_amount_pct)
        if df is None:
            return None
        return validate_unique_keys(df, file_path.name, key_col, max_invalid_key_pct)
            
    except Exception as e:
        logger.error(f"💥 Error crítico leyendo {file_path.name}: {e}")
        raise UnreadableFile(file_path.name) from e

def _run_pipeline(config, reset_schema=False):
    summary = {"cargados": 0, "rechazados": 0, "filas": 0}
    inbox_dir = PROJECT_ROOT / config["paths"]["inbox"]
    archive_dir = PROJECT_ROOT / config["paths"]["archive"]
    rejected_dir = PROJECT_ROOT / config["paths"]["rejected"]
    inbox_dir.mkdir(parents=True, exist_ok=True)
    db_config = config["database"]
    engine = get_engine(db_config)
    schema = db_config["schema_raw"]
    analytics_schema = db_config["schema_analytics"]
    # Limites de tolerancia: se cambian en config/config.yaml (seccion "quality"), no aqui.
    max_invalid = config["quality"]["max_invalid_amount_pct"]
    max_key = config["quality"]["max_invalid_key_pct"]
    if reset_schema:
        drop_analytics_views(engine, analytics_schema)  # las vistas dependen de las tablas de raw
    init_schema(engine, schema, reset=reset_schema)
    create_analytics_views(engine, schema, analytics_schema)
    if reset_schema:
        logger.warning("♻️ Esquema reiniciado: tablas borradas y recreadas con el DDL de schema.py.")

    # "~$" = archivos temporales que Excel crea mientras un libro está abierto
    archivos_excel = sorted(p for p in inbox_dir.glob("*.xlsx") if not p.name.startswith("~$"))

    if not archivos_excel:
        logger.info("📭 Bandeja de entrada vacía: no hay archivos nuevos que procesar.")
        engine.dispose()
        return summary

    for archivo in archivos_excel:
        table = detect_table(archivo.stem)
        if table is None:
            logger.warning(f"⚠️ {archivo.name}: nombre no reconocido (debe contener: {', '.join(TABLE_RULES)}). Movido a '{rejected_dir.name}'.")
            move_file(archivo, rejected_dir)
            summary["rechazados"] += 1
            continue

        try:
            df_clean = process_file(archivo, max_invalid_amount_pct=max_invalid,
                                    max_invalid_key_pct=max_key, **TABLE_RULES[table])
        except UnreadableFile:
            # Probablemente corrupto o a medio copiar: se reintenta mañana, pero si lleva más de
            # 24 h en la bandeja ya no es temporal: se aparta para no alertar cada día.
            summary["rechazados"] += 1
            if time.time() - archivo.stat().st_mtime > 86400:
                move_file(archivo, rejected_dir)
            continue

        if df_clean is None:
            # Rechazado por calidad: se aparta para que un humano lo revise (y no se alerte cada día)
            move_file(archivo, rejected_dir)
            summary["rechazados"] += 1
        elif save_to_postgres(df_clean, table, engine, schema):
            summary["cargados"] += 1
            summary["filas"] += len(df_clean)
            move_file(archivo, archive_dir)
        else:
            # Fallo de base de datos (posiblemente temporal): se queda en la bandeja y se reintenta mañana
            summary["rechazados"] += 1

    engine.dispose()
    logger.info("🏁 Pipeline finalizado.")
    return summary

def run_pipeline(reset_schema=False):
    """Ejecuta el pipeline y, al final, envía una tarjeta a Discord: verde si todo salió bien,
    roja si hubo errores o el pipeline abortó."""
    config = load_config()
    collector = IssueCollector()
    logger.addHandler(collector)
    summary, aborted = {"cargados": 0, "rechazados": 0, "filas": 0}, False
    try:
        summary = _run_pipeline(config, reset_schema)
    except Exception as e:
        aborted = True
        logger.error(f"💥 Pipeline abortado: {e}")
        raise
    finally:
        logger.removeHandler(collector)  # que la notificación no se cuente a sí misma
        alerts_cfg = config["alerts"]
        notify_run(summary, collector.issues, collector.errors, aborted, logger,
                   notify_on_success=alerts_cfg["notify_on_success"],
                   environment=alerts_cfg["environment"])

if __name__ == "__main__":
    run_pipeline(reset_schema="--reset-schema" in sys.argv)