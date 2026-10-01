"""Herramientas del agente.

Cada herramienta declara su contrato con un modelo Pydantic: de él se genera el
JSON Schema que recibe el LLM (function calling) y se validan los argumentos
antes de ejecutar. Los errores se devuelven al LLM como datos para que pueda
corregirse, en vez de romper la conversación.
"""
from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.agent import rules
from app.core.logging import get_logger
from app.core.security import neutralize_context
from app.rag.knowledge_base import KnowledgeBase
from app.rag.text import tokenize
from app.rag.vectorstore import SearchResult
from app.storage.requests_repo import RequestRepository

log = get_logger(__name__)

REQUEST_ID_RE = re.compile(r"^SOL-\d{4}$", re.I)


# ---------------------------------------------------------------------------
# Contexto por ejecución
# ---------------------------------------------------------------------------
@dataclass
class ToolContext:
    kb: KnowledgeBase
    requests: RequestRepository
    cloud_catalog: list[dict]
    citations: list[SearchResult] = field(default_factory=list)  # registro de fuentes (ref = índice + 1)
    retrieval_attempted: bool = False

    def register(self, result: SearchResult) -> int:
        for i, c in enumerate(self.citations):
            if c.id == result.id:
                return i + 1
        self.citations.append(result)
        return len(self.citations)


# ---------------------------------------------------------------------------
# Argumentos
# ---------------------------------------------------------------------------
class _RequestIdArg(BaseModel):
    request_id: str = Field(description="Identificador de la solicitud con formato SOL-NNNN, p. ej. SOL-1003")

    @field_validator("request_id")
    @classmethod
    def _fmt(cls, v: str) -> str:
        v = v.strip().upper()
        if not REQUEST_ID_RE.match(v):
            raise ValueError("formato esperado SOL-NNNN")
        return v


class BuscarDocumentacionArgs(BaseModel):
    query: str = Field(min_length=3, max_length=500, description="Consulta en lenguaje natural, específica y autocontenida")
    top_k: int = Field(default=4, ge=1, le=8, description="Número de fragmentos a recuperar")


class ConsultarSolicitudArgs(_RequestIdArg):
    pass


class ResumenEjecutivoArgs(_RequestIdArg):
    pass


class ClasificarPrioridadArgs(BaseModel):
    request_id: str | None = Field(default=None, description="Solicitud existente a clasificar (SOL-NNNN). Opcional si se da descripción")
    descripcion: str | None = Field(default=None, max_length=2000, description="Descripción libre de una solicitud nueva")
    impacto: Literal["alto", "medio", "bajo"] | None = Field(default=None, description="Impacto, si se conoce")
    urgencia: Literal["alta", "media", "baja"] | None = Field(default=None, description="Urgencia, si se conoce")
    dias_para_fecha_limite: int | None = Field(default=None, ge=0, le=365, description="Días hábiles a la fecha límite (si aplica)")


class CalcularEsfuerzoArgs(BaseModel):
    request_id: str | None = Field(default=None, description="Solicitud existente (SOL-NNNN); si se da, sus datos completan los demás campos")
    tipo: Literal["consulta_reporte", "incidente", "cambio_menor", "nueva_funcionalidad", "integracion", "migracion"] | None = None
    complejidad: Literal["baja", "media", "alta"] | None = None
    sistemas_integrados: int | None = Field(default=None, ge=1, le=20)
    requiere_migracion_datos: bool | None = None


class RecomendarServiciosArgs(BaseModel):
    necesidad: str = Field(min_length=3, max_length=500, description="Necesidad técnica o componente a modernizar")
    proveedor: Literal["azure", "aws", "ambos"] = "azure"
    max_resultados: int = Field(default=3, ge=1, le=6)


# ---------------------------------------------------------------------------
# Implementaciones
# ---------------------------------------------------------------------------
def _safe(text: str) -> str:
    return neutralize_context(text or "")[0]


def buscar_documentacion(ctx: ToolContext, args: BuscarDocumentacionArgs) -> dict:
    ctx.retrieval_attempted = True
    results = ctx.kb.relevant(ctx.kb.retrieve(args.query, args.top_k))
    if not results:
        return {"resultados": [], "nota": "Sin fragmentos relevantes. No respondas con conocimiento propio."}
    fragments = []
    for r in results:
        ref = ctx.register(r)
        fragments.append({"ref": ref, "fuente": r.source, "seccion": r.section, "pagina": r.page,
                          "relevancia": r.score, "contenido": _safe(r.text)})
    out: dict = {"resultados": fragments}
    coverage = ctx.kb.query_coverage(args.query, results)
    if coverage is not None:
        out["cobertura_terminos"] = coverage
        if coverage < 0.6:
            out["nota"] = "Términos clave de la consulta no aparecen en los fragmentos; verifica si realmente responden."
    return out


def _public_request(req: dict) -> dict:
    allowed = ["id", "titulo", "estado", "tipo", "area_solicitante", "equipo_responsable", "impacto", "urgencia",
               "prioridad_registrada", "fecha_creacion", "fecha_actualizacion", "sistemas_afectados", "complejidad",
               "requiere_migracion_datos"]
    out = {k: req.get(k) for k in allowed if k in req}
    out["descripcion"] = _safe(req.get("descripcion", ""))
    out["historial"] = [{**h, "nota": _safe(h.get("nota", ""))} for h in req.get("historial", [])][-5:]
    return out


def consultar_solicitud(ctx: ToolContext, args: ConsultarSolicitudArgs) -> dict:
    req = ctx.requests.get(args.request_id)
    if not req:
        return {"error": f"No existe la solicitud {args.request_id}"}
    return {"solicitud": _public_request(req)}


def clasificar_prioridad(ctx: ToolContext, args: ClasificarPrioridadArgs) -> dict:
    descripcion, impacto, urgencia = args.descripcion or "", args.impacto, args.urgencia
    if args.request_id:
        req = ctx.requests.get(args.request_id)
        if not req:
            return {"error": f"No existe la solicitud {args.request_id}"}
        descripcion = f"{req.get('titulo', '')}. {req.get('descripcion', '')} {descripcion}"
        impacto = impacto or req.get("impacto")
        urgencia = urgencia or req.get("urgencia")
    if not descripcion and not (impacto and urgencia):
        return {"error": "Proporcione request_id, descripción o impacto y urgencia"}
    result = rules.classify_priority(impacto=impacto, urgencia=urgencia, descripcion=descripcion,
                                     dias_para_fecha_limite=args.dias_para_fecha_limite)
    if args.request_id:
        result["request_id"] = args.request_id.upper()
    return result


_TYPE_MAP = {"reporte": "consulta_reporte", "consulta": "consulta_reporte"}


def calcular_esfuerzo(ctx: ToolContext, args: CalcularEsfuerzoArgs) -> dict:
    tipo, complejidad = args.tipo, args.complejidad
    sistemas, migracion = args.sistemas_integrados, args.requiere_migracion_datos
    if args.request_id:
        req = ctx.requests.get(args.request_id)
        if not req:
            return {"error": f"No existe la solicitud {args.request_id}"}
        tipo = tipo or _TYPE_MAP.get(req.get("tipo"), req.get("tipo"))
        complejidad = complejidad or req.get("complejidad")
        sistemas = sistemas or len(req.get("sistemas_afectados", [])) or 1
        migracion = req.get("requiere_migracion_datos", False) if migracion is None else migracion
    if not tipo:
        return {"error": "Falta 'tipo' (o un request_id del cual inferirlo)"}
    try:
        result = rules.estimate_effort(tipo=tipo, complejidad=complejidad or "media",
                                       sistemas_integrados=sistemas or 1, requiere_migracion_datos=bool(migracion))
    except ValueError as exc:
        return {"error": str(exc)}
    if args.request_id:
        result["request_id"] = args.request_id.upper()
    return result


def resumen_ejecutivo(ctx: ToolContext, args: ResumenEjecutivoArgs) -> dict:
    req = ctx.requests.get(args.request_id)
    if not req:
        return {"error": f"No existe la solicitud {args.request_id}"}
    prio = clasificar_prioridad(ctx, ClasificarPrioridadArgs(request_id=args.request_id))
    effort = calcular_esfuerzo(ctx, CalcularEsfuerzoArgs(request_id=args.request_id))
    hist = req.get("historial", [])
    estado = req.get("estado", "")
    riesgos = []
    if estado.lower() == "bloqueada":
        riesgos.append("La solicitud está bloqueada: requiere decisión o insumo externo.")
    if req.get("requiere_migracion_datos"):
        riesgos.append("Incluye migración de datos: validar calidad y plan de reversa.")
    if prio.get("prioridad") in {"P1", "P2"} and estado.lower() in {"registrada", "en análisis"}:
        riesgos.append(f"Prioridad {prio['prioridad']} aún sin ejecución: riesgo de incumplir SLA.")
    return {
        "request_id": req["id"],
        "titulo": req.get("titulo"),
        "estado": estado,
        "area_solicitante": req.get("area_solicitante"),
        "equipo_responsable": req.get("equipo_responsable"),
        "prioridad": {k: prio.get(k) for k in ("prioridad", "nombre", "sla_resolucion")},
        "esfuerzo": {k: effort.get(k) for k in ("horas_estimadas", "dias_persona", "talla")},
        "ultima_novedad": _safe(hist[-1]["nota"]) if hist else None,
        "fecha_actualizacion": req.get("fecha_actualizacion"),
        "riesgos": riesgos or ["Sin riesgos relevantes identificados por reglas."],
        "descripcion": _safe(req.get("descripcion", "")),
    }


def recomendar_servicios_cloud(ctx: ToolContext, args: RecomendarServiciosArgs) -> dict:
    q = set(tokenize(args.necesidad))
    scored = []
    for item in ctx.cloud_catalog:
        kw = set(tokenize(" ".join(item.get("palabras_clave", [])) + " " + item.get("categoria", "") + " " + item.get("caso_de_uso", "")))
        overlap = len(q & kw)
        if overlap:
            scored.append((overlap, item))
    scored.sort(key=lambda x: -x[0])
    recs = []
    for _, item in scored[: args.max_resultados]:
        rec = {"categoria": item["categoria"], "caso_de_uso": item["caso_de_uso"], "consideraciones": item.get("consideraciones")}
        if args.proveedor in {"azure", "ambos"}:
            rec["azure"] = item["azure"]
        if args.proveedor in {"aws", "ambos"}:
            rec["aws"] = item["aws"]
        recs.append(rec)
    if not recs:
        return {"recomendaciones": [], "nota": "No hay servicios del catálogo aprobado que coincidan con la necesidad."}
    return {"recomendaciones": recs, "fuente": "Catálogo de servicios cloud aprobados (cloud_services.json)"}


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------
@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[ToolContext, Any], dict]

    def schema(self) -> dict:
        params = self.args_model.model_json_schema()
        params.pop("title", None)
        for prop in params.get("properties", {}).values():
            prop.pop("title", None)
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": params}}


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool("buscar_documentacion",
             "Busca en la documentación interna (manuales técnicos, procedimientos, políticas, históricos). "
             "Úsala para cualquier pregunta de conocimiento. Devuelve fragmentos con número 'ref' para citar.",
             BuscarDocumentacionArgs, buscar_documentacion),
        Tool("consultar_solicitud",
             "Consulta el estado, datos e historial de una solicitud del sistema legado por su id (SOL-NNNN).",
             ConsultarSolicitudArgs, consultar_solicitud),
        Tool("clasificar_prioridad",
             "Clasifica la prioridad (P1-P4) y SLA de una solicitud existente o de una descripción nueva, "
             "según la matriz impacto x urgencia y las reglas de ajuste oficiales.",
             ClasificarPrioridadArgs, clasificar_prioridad),
        Tool("calcular_esfuerzo",
             "Estima horas, días-persona y talla (S/M/L/XL) según la Guía de Estimación, a partir de una "
             "solicitud existente o de parámetros (tipo, complejidad, sistemas, migración de datos).",
             CalcularEsfuerzoArgs, calcular_esfuerzo),
        Tool("resumen_ejecutivo",
             "Genera un resumen ejecutivo de una solicitud: estado, prioridad, esfuerzo, última novedad y riesgos.",
             ResumenEjecutivoArgs, resumen_ejecutivo),
        Tool("recomendar_servicios_cloud",
             "Recomienda servicios cloud del catálogo aprobado (Azure y/o AWS) para una necesidad de modernización.",
             RecomendarServiciosArgs, recomendar_servicios_cloud),
    ]
}


def tool_schemas() -> list[dict]:
    return [t.schema() for t in TOOLS.values()]


@dataclass
class ToolExecution:
    name: str
    arguments: dict
    result: dict
    ok: bool
    elapsed_ms: int


def execute_tool(ctx: ToolContext, name: str, raw_arguments: str) -> ToolExecution:
    t0 = time.perf_counter()
    tool = TOOLS.get(name)
    try:
        parsed = json.loads(raw_arguments or "{}")
        if not isinstance(parsed, dict):
            raise ValueError("los argumentos deben ser un objeto JSON")
    except (json.JSONDecodeError, ValueError) as exc:
        parsed, result, ok = {}, {"error": f"Argumentos JSON inválidos: {exc}"}, False
    else:
        if tool is None:
            result, ok = {"error": f"Herramienta desconocida: {name}. Disponibles: {sorted(TOOLS)}"}, False
        else:
            try:
                args = tool.args_model.model_validate(parsed)
                result = tool.fn(ctx, args)
                ok = "error" not in result
            except ValidationError as exc:
                result = {"error": "Argumentos inválidos", "detalle": [e["msg"] for e in exc.errors()]}
                ok = False
            except Exception:
                log.exception("tool_failed", extra={"tool": name})
                result, ok = {"error": "La herramienta falló internamente"}, False
    elapsed = int((time.perf_counter() - t0) * 1000)
    log.info("tool_executed", extra={"tool": name, "ok": ok, "elapsed_ms": elapsed, "tool_args": parsed})
    return ToolExecution(name=name, arguments=parsed, result=result, ok=ok, elapsed_ms=elapsed)
