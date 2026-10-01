"""Integración opcional con Azure Monitor / Application Insights.

Si existe APPLICATIONINSIGHTS_CONNECTION_STRING se activa OpenTelemetry con el
distro de Azure Monitor: trazas de requests FastAPI, dependencias HTTP (Azure
OpenAI, AI Search) y logs. Sin la variable, la app funciona igual con logging
JSON a stdout (que Container Apps también envía a Log Analytics).
"""
from __future__ import annotations

from app.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


def configure_telemetry(settings: Settings) -> bool:
    if not settings.applicationinsights_connection_string:
        log.info("telemetry_disabled", extra={"reason": "sin APPLICATIONINSIGHTS_CONNECTION_STRING"})
        return False
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=settings.applicationinsights_connection_string.get_secret_value(),
            logger_name="app",
        )
        log.info("telemetry_enabled", extra={"backend": "application_insights"})
        return True
    except Exception:  # pragma: no cover - depende del entorno
        log.exception("telemetry_init_failed")
        return False
