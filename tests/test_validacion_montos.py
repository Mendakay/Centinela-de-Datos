"""Tests de validate_amounts. Ejecutar desde la raíz del proyecto:
    .venv\\Scripts\\python.exe -m pytest tests -v
"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pipeline import validate_amounts, validate_unique_keys  # noqa: E402


def test_clave_repetida_conserva_la_primera_y_aparta_el_resto():
    df = pd.DataFrame({"id": list(range(1, 100)) + [1], "v": range(100)})  # 1 repetido de 100
    out = validate_unique_keys(df, "t.xlsx", "id", max_invalid_pct=0.05)
    assert len(out) == 99
    assert out["id"].is_unique
    assert out.iloc[0]["v"] == 0  # se quedó la primera aparición


def test_muchas_claves_repetidas_rechazan_el_archivo():
    df = pd.DataFrame({"id": [1] * 50 + list(range(2, 52))})  # 49 repetidos de 100
    assert validate_unique_keys(df, "t.xlsx", "id", max_invalid_pct=0.05) is None


def test_clave_nula_se_aparta():
    df = pd.DataFrame({"id": list(range(1, 100)) + [None]})
    out = validate_unique_keys(df, "t.xlsx", "id", max_invalid_pct=0.05)
    assert len(out) == 99


def test_sin_columna_clave_no_hace_nada():
    df = pd.DataFrame({"x": [1, 1]})
    assert len(validate_unique_keys(df, "t.xlsx", None)) == 2


def test_montos_validos_pasan_intactos():
    df = pd.DataFrame({"monto_venta": [10.0, 0.0, 250.5]})  # el 0 es válido
    out = validate_amounts(df, "t.xlsx", ["monto_venta"])
    assert len(out) == 3


def test_pocos_negativos_se_apartan_y_el_resto_pasa():
    # 1 negativo de 100 filas = 1% < umbral 5%
    df = pd.DataFrame({"monto_venta": [100.0] * 99 + [-5.0]})
    out = validate_amounts(df, "t.xlsx", ["monto_venta"], max_invalid_pct=0.05)
    assert len(out) == 99
    assert (out["monto_venta"] >= 0).all()


def test_muchos_negativos_rechazan_el_archivo_completo():
    # 20% negativos > umbral 5% -> None
    df = pd.DataFrame({"monto_venta": [100.0] * 80 + [-5.0] * 20})
    assert validate_amounts(df, "t.xlsx", ["monto_venta"], max_invalid_pct=0.05) is None


def test_nulos_no_numericos_cuentan_como_invalidos():
    df = pd.DataFrame({"precio_unitario": [10.0] * 99 + [float("nan")]})
    out = validate_amounts(df, "t.xlsx", ["precio_unitario"], max_invalid_pct=0.05)
    assert len(out) == 99


def test_columna_inexistente_se_ignora():
    df = pd.DataFrame({"otra": [1, 2, 3]})
    assert len(validate_amounts(df, "t.xlsx", ["monto_venta"])) == 3
