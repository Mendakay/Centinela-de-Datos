"""Definición explícita de las tablas del esquema raw (tipos, claves primarias, restricciones).

to_sql con if_exists="replace" infería tipos flojos (dinero como double precision) y no creaba
claves primarias. Aquí definimos el DDL una sola vez; el pipeline solo hace TRUNCATE + append.
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, MetaData, Numeric, String, Table, Text,
)


def build_tables(schema):
    metadata = MetaData(schema=schema)

    Table(
        "ventas", metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("fecha_venta", Date),
        Column("nombre_cliente", Text),
        Column("monto_venta", Numeric(12, 2), nullable=False),
        CheckConstraint("monto_venta >= 0", name="ck_ventas_monto_no_negativo"),
    )
    Table(
        "clientes", metadata,
        Column("id_cliente", BigInteger, primary_key=True, autoincrement=False),
        Column("nombre_cliente", Text),
        Column("fecha_alta", Date),
    )
    Table(
        "productos", metadata,
        Column("sku", String(20), primary_key=True),
        Column("descripcion_producto", Text),
        Column("precio_unitario", Numeric(12, 2), nullable=False),
        Column("fecha_ingreso_producto", Date),
        CheckConstraint("precio_unitario >= 0", name="ck_productos_precio_no_negativo"),
    )
    return metadata


def init_schema(engine, schema, reset=False):
    """Crea las tablas si no existen. Con reset=True las BORRA y recrea (destruye datos)."""
    metadata = build_tables(schema)
    if reset:
        metadata.drop_all(engine)
    metadata.create_all(engine)  # checkfirst=True: no toca tablas existentes
    return metadata
