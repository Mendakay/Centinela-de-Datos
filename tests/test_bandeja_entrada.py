"""Tests de la bandeja de entrada: detección del tipo de archivo y movimiento de archivos."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import alerts  # noqa: E402
from pipeline import detect_table, move_file  # noqa: E402


def test_detecta_el_tipo_por_el_nombre():
    assert detect_table("ventas_2024") == "ventas"
    assert detect_table("Ventas_Enero_2025") == "ventas"      # mayúsculas
    assert detect_table("clientes_sucio") == "clientes"
    assert detect_table("productos_v2") == "productos"


def test_nombre_no_reconocido_devuelve_none():
    assert detect_table("inventario_2025") is None
    assert detect_table("Libro1") is None


def test_move_file_mueve_y_antepone_fecha(tmp_path):
    origen = tmp_path / "ventas_enero.xlsx"
    origen.write_text("x")
    destino = move_file(origen, tmp_path / "archive")
    assert not origen.exists()
    assert destino.exists()
    assert destino.name.endswith("_ventas_enero.xlsx")
    assert destino.name != "ventas_enero.xlsx"


def test_move_file_no_pisa_un_archivo_anterior_con_el_mismo_nombre(tmp_path, monkeypatch):
    # Dos archivos con el mismo nombre en momentos distintos acaban como dos archivos distintos
    from datetime import datetime as real_dt
    import pipeline

    class Reloj:
        horas = iter(["20260101_070000", "20260102_070000"])

        @classmethod
        def now(cls):
            return real_dt.strptime(next(cls.horas), "%Y%m%d_%H%M%S")

    monkeypatch.setattr(pipeline, "datetime", Reloj)
    for contenido in ("uno", "dos"):
        f = tmp_path / "ventas.xlsx"
        f.write_text(contenido)
        move_file(f, tmp_path / "archive")
    assert len(list((tmp_path / "archive").iterdir())) == 2


def test_move_file_fallido_no_lanza_excepcion(tmp_path):
    # Si el archivo no existe (o está bloqueado) solo avisa; no rompe el pipeline
    assert move_file(tmp_path / "no_existe.xlsx", tmp_path / "archive") is None


def test_tarjeta_con_bandeja_vacia_lo_dice_claramente():
    p = alerts.build_payload(False, {"cargados": 0, "rechazados": 0, "filas": 0}, [])
    e = p["embeds"][0]
    assert "No había archivos nuevos" in e["description"]
    campos = {f["name"]: f["value"] for f in e["fields"]}
    assert campos["Archivos procesados"] == "Ninguno nuevo"
