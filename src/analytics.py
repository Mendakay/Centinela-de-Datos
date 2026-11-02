"""Capa analytics: vistas SQL listas para reportes, construidas sobre las tablas de raw.

Se usan VISTAS (no tablas copia): no guardan datos, siempre muestran lo último que hay en raw
y no hay nada que refrescar ni sincronizar.
"""
from sqlalchemy import text

VIEWS = {
    "ventas_por_mes": """
        CREATE OR REPLACE VIEW "{a}".ventas_por_mes AS
        SELECT date_trunc('month', fecha_venta)::date AS mes,
               count(*)                               AS num_ventas,
               sum(monto_venta)                       AS monto_total,
               round(avg(monto_venta), 2)             AS ticket_promedio
        FROM "{r}".ventas
        WHERE fecha_venta IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """,
    "ventas_por_cliente": """
        CREATE OR REPLACE VIEW "{a}".ventas_por_cliente AS
        SELECT nombre_cliente,
               count(*)         AS num_compras,
               sum(monto_venta) AS monto_total,
               max(fecha_venta) AS ultima_compra
        FROM "{r}".ventas
        WHERE nombre_cliente IS NOT NULL
        GROUP BY nombre_cliente
        ORDER BY monto_total DESC
    """,
}


def drop_analytics_views(engine, analytics_schema):
    """Necesario antes de borrar tablas de raw (PostgreSQL no deja borrar tablas con vistas encima)."""
    with engine.begin() as conn:
        for name in VIEWS:
            conn.execute(text(f'DROP VIEW IF EXISTS "{analytics_schema}"."{name}"'))


def create_analytics_views(engine, raw_schema, analytics_schema):
    """Crea o actualiza las vistas (idempotente)."""
    with engine.begin() as conn:
        for sql in VIEWS.values():
            conn.execute(text(sql.format(r=raw_schema, a=analytics_schema)))
