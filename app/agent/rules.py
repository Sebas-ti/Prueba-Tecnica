"""Reglas de negocio deterministas usadas por las herramientas.

Están alineadas con los documentos `procedimiento_gestion_solicitudes.md` y
`guia_estimacion_esfuerzo.md` del corpus, de modo que lo que el agente
calcula con herramientas coincide con lo que la documentación dice. Un LLM no
debe "calcular" prioridades ni esfuerzos: estas reglas son auditables y
testeables.
"""
from __future__ import annotations

import math
import re
from typing import Literal

Level = Literal["alto", "medio", "bajo"]
Urgency = Literal["alta", "media", "baja"]

# Matriz impacto x urgencia
_MATRIX: dict[tuple[str, str], str] = {
    ("alto", "alta"): "P1", ("alto", "media"): "P2", ("alto", "baja"): "P3",
    ("medio", "alta"): "P2", ("medio", "media"): "P3", ("medio", "baja"): "P4",
    ("bajo", "alta"): "P3", ("bajo", "media"): "P4", ("bajo", "baja"): "P4",
}

PRIORITY_INFO = {
    "P1": {"nombre": "Crítica", "sla_respuesta": "1 hora", "sla_resolucion": "8 horas"},
    "P2": {"nombre": "Alta", "sla_respuesta": "4 horas", "sla_resolucion": "2 días hábiles"},
    "P3": {"nombre": "Media", "sla_respuesta": "1 día hábil", "sla_resolucion": "5 días hábiles"},
    "P4": {"nombre": "Baja", "sla_respuesta": "2 días hábiles", "sla_resolucion": "10 días hábiles"},
}

_SECURITY_KW = re.compile(r"\b(seguridad|vulnerabilidad|fuga|brecha|acceso no autorizado|phishing|malware|ransomware)\b", re.I)
_OUTAGE_KW = re.compile(r"\b(ca[ií]d[oa]s?|no disponible|indisponib|fuera de servicio|producci[oó]n detenida|bloquead[oa])\b", re.I)
_REGULATORY_KW = re.compile(r"\b(regulator|normativ|superintendencia|auditor[ií]a externa|ley)\w*", re.I)


def _infer_impact(text: str) -> Level:
    explicit = re.search(r"impacto\W{0,3}(alto|medio|bajo)", text, re.I)
    if explicit:
        return explicit.group(1).lower()  # type: ignore[return-value]
    if _OUTAGE_KW.search(text) or re.search(r"\b(toda la (organizaci[oó]n|compa[ñn][ií]a)|todos los usuarios|clientes)\b", text, re.I):
        return "alto"
    if re.search(r"\b([aá]rea|equipo|departamento|varios usuarios)\b", text, re.I):
        return "medio"
    return "bajo"


def _infer_urgency(text: str) -> Urgency:
    explicit = re.search(r"urgencia\W{0,3}(alta|media|baja)", text, re.I)
    if explicit:
        return explicit.group(1).lower()  # type: ignore[return-value]
    if re.search(r"\b(urgente|inmediat|hoy|ya mismo|cr[ií]tico)\w*", text, re.I) or _OUTAGE_KW.search(text):
        return "alta"
    if re.search(r"\b(esta semana|pronto|pr[oó]ximos d[ií]as)\b", text, re.I):
        return "media"
    return "baja"


def classify_priority(
    *, impacto: str | None = None, urgencia: str | None = None, descripcion: str = "",
    dias_para_fecha_limite: int | None = None,
) -> dict:
    inferred = []
    imp = (impacto or "").lower() or None
    urg = (urgencia or "").lower() or None
    if imp not in {"alto", "medio", "bajo"}:
        imp = _infer_impact(descripcion)
        inferred.append("impacto")
    if urg not in {"alta", "media", "baja"}:
        urg = _infer_urgency(descripcion)
        inferred.append("urgencia")
    priority = _MATRIX[(imp, urg)]
    reasons = [f"Matriz impacto ({imp}) x urgencia ({urg}) => {priority}"]

    if dias_para_fecha_limite is None:
        m = re.search(r"(?:vence|l[ií]mite)\D{0,30}?(\d{1,3})\s*d[ií]as", descripcion, re.I)
        if m:
            dias_para_fecha_limite = int(m.group(1))

    # Reglas de ajuste (sección 4.3 del procedimiento)
    if _SECURITY_KW.search(descripcion) and priority in {"P3", "P4"}:
        priority = "P2"
        reasons.append("Regla 4.3.a: incidentes de seguridad se elevan mínimo a P2")
    if _OUTAGE_KW.search(descripcion) and imp == "alto":
        priority = "P1"
        reasons.append("Regla 4.3.b: indisponibilidad de producción con impacto alto => P1")
    if _REGULATORY_KW.search(descripcion) and dias_para_fecha_limite is not None and dias_para_fecha_limite < 5:
        priority = "P1"
        reasons.append("Regla 4.3.c: requerimiento regulatorio con fecha límite < 5 días hábiles => P1")

    return {
        "prioridad": priority,
        **PRIORITY_INFO[priority],
        "impacto": imp,
        "urgencia": urg,
        "campos_inferidos": inferred,
        "justificacion": reasons,
    }


BASE_HOURS = {
    "consulta_reporte": 8,
    "incidente": 4,
    "cambio_menor": 16,
    "nueva_funcionalidad": 40,
    "integracion": 60,
    "migracion": 80,
}
COMPLEXITY_FACTOR = {"baja": 1.0, "media": 1.5, "alta": 2.5}
HOURS_PER_DAY = 6  # horas productivas por persona/día
CONTINGENCY = 0.15


def estimate_effort(
    *, tipo: str, complejidad: str = "media", sistemas_integrados: int = 1, requiere_migracion_datos: bool = False,
) -> dict:
    tipo, complejidad = tipo.lower(), complejidad.lower()
    if tipo not in BASE_HOURS:
        raise ValueError(f"tipo inválido; use uno de {sorted(BASE_HOURS)}")
    if complejidad not in COMPLEXITY_FACTOR:
        raise ValueError(f"complejidad inválida; use uno de {sorted(COMPLEXITY_FACTOR)}")
    sistemas_integrados = max(1, int(sistemas_integrados))

    base = BASE_HOURS[tipo]
    hours = base * COMPLEXITY_FACTOR[complejidad]
    steps = [f"Base '{tipo}': {base} h", f"x factor complejidad '{complejidad}' ({COMPLEXITY_FACTOR[complejidad]}) = {hours:.1f} h"]
    extra_systems = sistemas_integrados - 1
    if extra_systems:
        hours += 8 * extra_systems
        steps.append(f"+ 8 h por cada sistema adicional ({extra_systems}) = {hours:.1f} h")
    if requiere_migracion_datos:
        hours *= 1.20
        steps.append(f"+ 20% por migración de datos = {hours:.1f} h")
    hours *= 1 + CONTINGENCY
    steps.append(f"+ 15% contingencia (QA y pruebas) = {hours:.1f} h")
    total = math.ceil(hours)
    size = "S" if total <= 24 else "M" if total <= 80 else "L" if total <= 200 else "XL"
    return {
        "horas_estimadas": total,
        "dias_persona": round(total / HOURS_PER_DAY, 1),
        "talla": size,
        "desglose": steps,
        "supuestos": "6 h productivas por día-persona; reglas de la Guía de Estimación v2.",
    }
