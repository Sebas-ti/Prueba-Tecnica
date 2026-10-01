"""Logging estructurado (JSON) con correlation id y redacción de PII.

- Cada línea de log es un JSON (compatible con Application Insights,
  Log Analytics, CloudWatch o cualquier agregador).
- El `request_id` se propaga con contextvars para correlacionar todas las
  trazas de una misma petición.
- Antes de escribir, se redactan patrones de datos sensibles (correos,
  teléfonos, tarjetas, claves) para evitar fuga de datos en los logs.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_PII_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
    # El código de país es opcional como grupo completo (no solo el '+'): un
    # celular de 10 dígitos sin separadores ("3001234567") también debe calzar,
    # no solo variantes con "+57 300 123 4567" (encontrado probando en vivo).
    (re.compile(r"(?<!\w)(?:\+?\d{1,3}[ -]?)?\(?\d{3}\)?[ -]?\d{3}[ -]?\d{4}(?!\w)"), "[PHONE]"),
    (re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "[REDACTED_KEY]"),
]


def redact(text: str) -> str:
    for pattern, repl in _PII_PATTERNS:
        text = pattern.sub(repl, text)
    return text


class JsonFormatter(logging.Formatter):
    _RESERVED = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "msg": redact(record.getMessage()),
        }
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                payload[key] = redact(value) if isinstance(value, str) else value
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Librerías ruidosas
    for noisy in ("httpx", "azure", "urllib3", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
