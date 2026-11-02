"""Tests de alerts.py. No envían nada real a Discord: se simula la red."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import alerts  # noqa: E402

log = logging.getLogger("test_alertas")
RESUMEN_OK = {"cargados": 3, "rechazados": 0, "filas": 3600}


def _campos(payload):
    return {f["name"]: f["value"] for f in payload["embeds"][0]["fields"]}


def test_tarjeta_verde_de_exito_con_numeros_reales():
    p = alerts.build_payload(False, RESUMEN_OK, [])
    e = p["embeds"][0]
    assert p["username"] == "Centinela de Datos"
    assert e["color"] == alerts.COLOR_OK == 5763719
    assert "ÉXITO" in e["title"]
    assert _campos(p)["Estado"] == "Completado"
    assert _campos(p)["Archivos procesados"] == "3 de 3 cargados"
    assert _campos(p)["Filas cargadas"] == "3,600"
    assert e["timestamp"].endswith("+00:00")  # UTC explícito, no hora local ambigua


def test_tarjeta_roja_de_fallo():
    p = alerts.build_payload(True, {"cargados": 1, "rechazados": 2, "filas": 1200}, ["❌ ventas rechazado"])
    e = p["embeds"][0]
    assert e["color"] == alerts.COLOR_ERROR == 15548997
    assert "FALLO" in e["title"]
    assert _campos(p)["Estado"] == "Fallido"
    assert _campos(p)["Archivos procesados"] == "1 de 3 cargados"  # no dice "3 Excel" a ciegas
    assert "ventas rechazado" in e["description"]


def test_exito_con_avisos_sigue_verde_pero_lo_dice():
    p = alerts.build_payload(False, RESUMEN_OK, ["🧹 2 filas apartadas"])
    assert p["embeds"][0]["color"] == alerts.COLOR_OK
    assert _campos(p)["Estado"] == "Completado con avisos"


def test_mensaje_largo_se_recorta_para_discord():
    p = alerts.build_payload(True, RESUMEN_OK, ["x" * 500] * 40)
    assert len(p["embeds"][0]["description"]) <= alerts.DESCRIPTION_LIMIT


def test_exito_sin_notify_on_success_no_envia(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/hook")
    enviados = []
    monkeypatch.setattr(alerts, "send_discord", lambda *a, **k: enviados.append(1))
    assert alerts.notify_run(RESUMEN_OK, [], 0, False, log, notify_on_success=False) is False
    assert enviados == []


def test_exito_con_notify_on_success_envia(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/hook")
    enviados = []
    monkeypatch.setattr(alerts, "send_discord", lambda payload, url, **k: enviados.append(payload) or True)
    assert alerts.notify_run(RESUMEN_OK, [], 0, False, log, notify_on_success=True) is True
    assert enviados[0]["embeds"][0]["color"] == alerts.COLOR_OK


def test_pipeline_abortado_envia_tarjeta_roja(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/hook")
    enviados = []
    monkeypatch.setattr(alerts, "send_discord", lambda payload, url, **k: enviados.append(payload) or True)
    alerts.notify_run({}, ["💥 Pipeline abortado: sin conexión"], 1, True, log)
    assert enviados[0]["embeds"][0]["color"] == alerts.COLOR_ERROR


def test_sin_webhook_no_envia_ni_falla(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert alerts.notify_run(RESUMEN_OK, [], 0, False, log) is False


def test_fallo_de_red_nunca_rompe_el_pipeline(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/hook")

    def boom(*a, **k):
        raise OSError("sin internet")

    monkeypatch.setattr(alerts, "send_discord", boom)
    assert alerts.notify_run(RESUMEN_OK, [], 0, False, log) is False  # no lanza


def test_collector_cuenta_errores_y_guarda_warnings():
    collector = alerts.IssueCollector()
    lg = logging.getLogger("test_collector")
    lg.setLevel(logging.DEBUG)
    lg.addHandler(collector)
    lg.info("normal")
    lg.warning("aviso")
    lg.error("error")
    lg.removeHandler(collector)
    assert collector.issues == ["aviso", "error"]
    assert collector.errors == 1
