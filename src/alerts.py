"""Notificaciones por Webhook de Discord (tarjetas / embeds).

Principio: una notificación que falla NUNCA debe romper el pipeline. Si no hay webhook
configurado o el envío falla, solo se registra en el log.
"""
import json
import logging
import os
import urllib.request
from datetime import datetime, timezone

COLOR_ERROR = 15548997   # rojo (decimal)
COLOR_OK = 5763719       # verde (decimal)
MAX_ISSUE_LINES = 12
DESCRIPTION_LIMIT = 3500  # Discord permite 4096 en la descripción de un embed


class IssueCollector(logging.Handler):
    """Guarda los mensajes WARNING y ERROR de una corrida y cuenta cuántos fueron ERROR."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.issues = []
        self.errors = 0

    def emit(self, record):
        self.issues.append(record.getMessage())
        if record.levelno >= logging.ERROR:
            self.errors += 1


def build_payload(es_error, summary, issues, environment="Local / Desarrollo"):
    """Arma la tarjeta de Discord. Los números salen de la corrida real, nada fijo."""
    cargados = summary.get("cargados", 0)
    rechazados = summary.get("rechazados", 0)
    total = cargados + rechazados

    if es_error:
        titulo = "❌ FALLO EN EL PIPELINE"
        estado = "Fallido"
    else:
        titulo = "✅ PIPELINE EJECUTADO CON ÉXITO"
        estado = "Completado con avisos" if issues else "Completado"

    if issues:
        lines = [f"• {m}" for m in issues[:MAX_ISSUE_LINES]]
        if len(issues) > MAX_ISSUE_LINES:
            lines.append(f"... y {len(issues) - MAX_ISSUE_LINES} más (ver logs/centinela.log)")
        descripcion = "\n".join(lines)[:DESCRIPTION_LIMIT]
    elif total == 0:
        descripcion = "No había archivos nuevos en la bandeja de entrada."
    else:
        descripcion = "Todos los archivos pasaron los controles de calidad."

    return {
        "username": "Centinela de Datos",
        "embeds": [{
            "title": titulo,
            "description": descripcion,
            "color": COLOR_ERROR if es_error else COLOR_OK,
            "fields": [
                {"name": "Estado", "value": estado, "inline": True},
                {"name": "Archivos procesados",
                 "value": f"{cargados} de {total} cargados" if total else "Ninguno nuevo", "inline": True},
                {"name": "Filas cargadas", "value": f"{summary.get('filas', 0):,}", "inline": True},
                {"name": "Entorno", "value": environment, "inline": True},
            ],
            # UTC explícito: Discord lo convierte a la zona horaria de quien lo mira
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "footer": {"text": "Sistema de Monitoreo Automático"},
        }],
    }


def send_discord(payload, webhook_url, timeout=10):
    """Envía el payload. Discord responde 204 si todo va bien. Devuelve True si fue aceptado."""
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "CentinelaDeDatos/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return 200 <= resp.status < 300


def notify_run(summary, issues, errors, aborted, logger, notify_on_success=True,
               environment="Local / Desarrollo"):
    """Envía la tarjeta al final de la corrida. Nunca lanza excepciones.
    Rojo si el pipeline abortó o hubo algún ERROR; verde en caso contrario."""
    es_error = aborted or errors > 0
    if not es_error and not issues and not notify_on_success:
        return False

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        logger.info("ℹ️ DISCORD_WEBHOOK_URL no está configurada: no se envió notificación.")
        return False
    try:
        send_discord(build_payload(es_error, summary, issues, environment), webhook_url)
        logger.info("📣 Notificación enviada a Discord.")
        return True
    except Exception as e:
        logger.error(f"💥 No se pudo enviar la notificación a Discord: {e}")
        return False
