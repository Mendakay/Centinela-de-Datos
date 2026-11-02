import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import pipeline  # noqa: E402


def test_fecha_serial_de_excel_no_cae_en_1970():
    df = pipeline.standardize_dates(pd.DataFrame({"f": [45000]}), ["f"])
    assert df["f"].iloc[0] == pd.Timestamp("2023-03-15")


def test_nulos_reales_no_se_vuelven_texto_none():
    df = pipeline.clean_strings(pd.DataFrame({"n": ["  Ana   Paz ", None]}))
    assert df["n"].iloc[0] == "Ana Paz"
    assert pd.isna(df["n"].iloc[1])


def test_encabezado_con_espacio_se_acepta(tmp_path):
    f = tmp_path / "ventas_x.xlsx"
    pd.DataFrame({"id": [1], "fecha ": ["15/03/2024"], "monto": [10.0]}).to_excel(f, index=False)
    df = pipeline.process_file(f, **pipeline.TABLE_RULES["ventas"])
    assert df is not None and len(df) == 1


def test_excel_sin_columna_obligatoria_se_rechaza(tmp_path):
    f = tmp_path / "ventas_y.xlsx"
    pd.DataFrame({"id": [1], "fecha": ["15/03/2024"]}).to_excel(f, index=False)
    assert pipeline.process_file(f, **pipeline.TABLE_RULES["ventas"]) is None
