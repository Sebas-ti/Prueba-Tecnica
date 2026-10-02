"""LLM local determinista ("modo offline").

Emula el contrato de un LLM con function calling para que la solución completa
(API, agente, herramientas, trazabilidad, evaluación) pueda ejecutarse y
probarse sin credenciales de Azure:

- **Planificación**: decide qué herramientas llamar con reglas de intención.
- **Composición**: redacta la respuesta final de forma *extractiva* a partir de
  los resultados de las herramientas (nunca agrega información que no esté en
  ellos) y cita las fuentes con [n].

No es un sustituto de GPT-4o; es un doble de prueba realista que además sirve
como línea base de evaluación. En Azure se usa `AzureOpenAILLM`.
"""
from __future__ import annotations

import json
import math
import re
import uuid

from app.llm.base import LLMResponse, ToolCall
from app.llm.prompts import NO_INFO_ANSWER
from app.rag.text import split_sentences, strip_accents, tokenize

_ID = re.compile(r"\bSOL-\d{4}\b", re.I)

_INTENTS = {
    "resumen_ejecutivo": re.compile(r"\b(resumen|resume|resumir|sintesis|ejecutivo)\b"),
    "clasificar_prioridad": re.compile(r"\b(clasific\w*|prioriza\w*|que prioridad|cual (es la|seria la) prioridad|prioridad (tiene|tendria|le corresponde|deberia|asignar))\b"),
    "calcular_esfuerzo": re.compile(r"\b(esfuerzo|estim\w*|cuantas horas|cuanto (tiempo|tardar\w*)|talla)\b"),
    "consultar_solicitud": re.compile(r"\b(estado|como va|en que va|historial|avance|consulta\w* la solicitud)\b"),
    "recomendar_servicios_cloud": re.compile(r"\b(servicios? (cloud|en la nube|de azure|de aws|gestionados?)|que servicios?|recomienda\w*.{0,40}(azure|aws|nube|cloud))\b"),
}
_EFFORT_TYPES = {
    "migracion": r"migra", "integracion": r"integra", "nueva_funcionalidad": r"nueva funcionalidad|funcionalidad nueva|modulo nuevo",
    "cambio_menor": r"cambio menor|ajuste", "consulta_reporte": r"reporte|consulta", "incidente": r"incidente",
}


def _norm(text: str) -> str:
    return strip_accents(text.lower())


class LocalLLM:
    model_name = "local-deterministic-v1"

    # ------------------------------------------------------------------ API
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        last_user_idx = max(i for i, m in enumerate(messages) if m["role"] == "user")
        question = messages[last_user_idx]["content"]
        tool_results = self._tool_results(messages[last_user_idx + 1 :])
        if tools and not tool_results:
            calls = self._plan(question, messages[:last_user_idx])
            if calls:
                return LLMResponse(content=None, tool_calls=calls, model=self.model_name)
        return LLMResponse(content=self._compose(question, tool_results), model=self.model_name)

    # ------------------------------------------------------------- planning
    def _plan(self, question: str, history: list[dict]) -> list[ToolCall]:
        q = _norm(question)
        ids = [i.upper() for i in _ID.findall(question)]
        if not ids:  # seguimiento conversacional: "¿y cuál es su prioridad?"
            for m in reversed(history):
                found = _ID.findall(m.get("content") or "")
                if found:
                    ids = [found[-1].upper()]
                    break
        intents = [name for name, rx in _INTENTS.items() if rx.search(q)]
        calls: list[ToolCall] = []

        def add(name: str, args: dict) -> None:
            calls.append(ToolCall(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=json.dumps(args, ensure_ascii=False)))

        explicit_ids = bool(_ID.search(question))
        if "resumen_ejecutivo" in intents and ids:
            for i in ids:
                add("resumen_ejecutivo", {"request_id": i})
            intents = [x for x in intents if x not in {"resumen_ejecutivo", "consultar_solicitud"}]
        if "clasificar_prioridad" in intents:
            for i in ids or [None]:
                add("clasificar_prioridad", {"request_id": i} if i else {"descripcion": question})
        if "calcular_esfuerzo" in intents:
            if ids:
                for i in ids:
                    add("calcular_esfuerzo", {"request_id": i})
            else:
                args: dict = {}
                for tipo, rx in _EFFORT_TYPES.items():
                    if re.search(rx, q):
                        args["tipo"] = tipo
                        break
                m = re.search(r"complejidad (baja|media|alta)", q)
                if m:
                    args["complejidad"] = m.group(1)
                m = re.search(r"(\d+) sistemas", q)
                if m:
                    args["sistemas_integrados"] = int(m.group(1))
                if re.search(r"migracion de datos|migrar datos", q):
                    args["requiere_migracion_datos"] = True
                if "tipo" in args:
                    add("calcular_esfuerzo", args)
        if "recomendar_servicios_cloud" in intents:
            prov = "ambos" if ("aws" in q and "azure" in q) else "aws" if "aws" in q else "azure"
            add("recomendar_servicios_cloud", {"necesidad": question, "proveedor": prov})
        if ids and (("consultar_solicitud" in intents) or (explicit_ids and not calls)):
            for i in ids:
                add("consultar_solicitud", {"request_id": i})
        if not calls:
            add("buscar_documentacion", {"query": question})
        return calls

    # ---------------------------------------------------------- composition
    @staticmethod
    def _tool_results(messages: list[dict]) -> list[tuple[str, dict]]:
        names: dict[str, str] = {}
        out = []
        for m in messages:
            if m["role"] == "assistant":
                for tc in m.get("tool_calls") or []:
                    names[tc["id"]] = tc["function"]["name"]
            elif m["role"] == "tool":
                out.append((names.get(m["tool_call_id"], "?"), json.loads(m["content"])))
        return out

    def _compose(self, question: str, results: list[tuple[str, dict]]) -> str:
        if not results:
            return NO_INFO_ANSWER
        parts = []
        for name, data in results:
            if "error" in data:
                parts.append(f"No pude completar `{name}`: {data['error']}.")
                continue
            formatter = getattr(self, f"_fmt_{name}", None)
            parts.append(formatter(question, data) if formatter else json.dumps(data, ensure_ascii=False))
        if results and all("error" in data for _, data in results):
            # Ninguna herramienta aportó datos reales (p. ej. "no existe la
            # solicitud"): es una abstención, no una respuesta con datos. El
            # prefijo estándar es lo que el agente usa para clasificar status=no_info.
            return NO_INFO_ANSWER + "\n\n" + "\n\n".join(parts)
        return "\n\n".join(p for p in parts if p)

    def _fmt_buscar_documentacion(self, question: str, data: dict) -> str:
        frags = data.get("resultados", [])
        if not frags:
            return NO_INFO_ANSWER
        q_tokens = set(tokenize(question))
        coverage = data.get("cobertura_terminos")
        if coverage is None:
            corpus_tokens = set(tokenize(" ".join(f["contenido"] for f in frags)))
            coverage = len(q_tokens & corpus_tokens) / max(len(q_tokens), 1)
        if coverage < 0.6:
            # El contexto recuperado no cubre la pregunta: mejor abstenerse.
            return NO_INFO_ANSWER
        # Términos "entidad" (con dígitos: P2, 2025, SOL-1003): la oración elegida
        # debe contenerlos; evita responder sobre P1 cuando se pregunta por P2.
        entities = {t for t in q_tokens if any(ch.isdigit() for ch in t)}
        candidates = []
        for f in frags:
            body = f["contenido"].split("\n", 1)[-1]
            prev_overlap = 0
            for pos, sent in enumerate(split_sentences(body)):
                sent = sent.strip(" -*•\t")
                toks = set(tokenize(sent))
                overlap = len(q_tokens & toks)
                # Arrastre de contexto: la oración que sigue a una muy relevante
                # (p. ej. un subtítulo "Decisión sobre la base de datos.") suele
                # contener la respuesta.
                carried = 0.5 * prev_overlap
                prev_overlap = overlap
                if len(sent) < 25 or "[contenido removido" in sent or (overlap + carried) == 0:
                    continue
                score = (overlap + carried) / math.sqrt(len(toks) + 1) + 0.5 * f["relevancia"] - 0.01 * pos
                if len(sent) < 45:
                    score *= 0.6  # frases cortas tipo título aportan poca información
                if entities:
                    score *= 1.6 if entities <= toks else 0.4
                candidates.append((score, f["ref"], sent))
        if not candidates:
            return NO_INFO_ANSWER
        candidates.sort(key=lambda c: -c[0])
        best = candidates[0][0]
        chosen, seen = [], set()
        for score, ref, sent in candidates:
            key = sent.lower()[:80]
            if score < 0.5 * best or key in seen:
                continue
            seen.add(key)
            chosen.append((ref, sent))
            if len(chosen) == 3:
                break
        lines = [f"- {s.rstrip('.')}. [{r}]" for r, s in chosen]
        return "Según la documentación interna:\n" + "\n".join(lines)

    @staticmethod
    def _fmt_consultar_solicitud(_: str, data: dict) -> str:
        s = data["solicitud"]
        last = s.get("historial", [])[-1] if s.get("historial") else None
        txt = (f"La solicitud **{s['id']}** — «{s.get('titulo')}» está en estado **{s.get('estado')}** "
               f"(última actualización: {s.get('fecha_actualizacion')}). Equipo responsable: {s.get('equipo_responsable')}; "
               f"área solicitante: {s.get('area_solicitante')}.")
        if last:
            txt += f"\nÚltima novedad ({last.get('fecha')}): {last.get('nota')}"
        return txt

    @staticmethod
    def _fmt_clasificar_prioridad(_: str, d: dict) -> str:
        head = f"Solicitud {d['request_id']}: " if d.get("request_id") else ""
        why = "; ".join(d.get("justificacion", []))
        inferred = f" (inferido de la descripción: {', '.join(d['campos_inferidos'])})" if d.get("campos_inferidos") else ""
        return (f"{head}prioridad **{d['prioridad']} ({d['nombre']})**. SLA de respuesta: {d['sla_respuesta']}; "
                f"SLA de resolución: {d['sla_resolucion']}.\nJustificación: {why}{inferred}.")

    @staticmethod
    def _fmt_calcular_esfuerzo(_: str, d: dict) -> str:
        head = f"Solicitud {d['request_id']}: " if d.get("request_id") else ""
        steps = "\n".join(f"  - {s}" for s in d.get("desglose", []))
        return (f"{head}esfuerzo estimado de **{d['horas_estimadas']} horas** "
                f"(~{d['dias_persona']} días-persona), talla **{d['talla']}**.\nDesglose:\n{steps}\nSupuestos: {d['supuestos']}")

    @staticmethod
    def _fmt_resumen_ejecutivo(_: str, d: dict) -> str:
        p, e = d["prioridad"], d["esfuerzo"]
        riesgos = "\n".join(f"  - {r}" for r in d["riesgos"])
        return (f"**Resumen ejecutivo — {d['request_id']}: {d['titulo']}**\n"
                f"- Estado: {d['estado']} (actualizado {d['fecha_actualizacion']})\n"
                f"- Área solicitante / responsable: {d['area_solicitante']} / {d['equipo_responsable']}\n"
                f"- Prioridad: {p['prioridad']} ({p['nombre']}), SLA de resolución {p['sla_resolucion']}\n"
                f"- Esfuerzo: {e['horas_estimadas']} h (~{e['dias_persona']} días-persona), talla {e['talla']}\n"
                f"- Última novedad: {d.get('ultima_novedad') or 'sin novedades'}\n"
                f"- Riesgos:\n{riesgos}")

    @staticmethod
    def _fmt_recomendar_servicios_cloud(_: str, d: dict) -> str:
        recs = d.get("recomendaciones", [])
        if not recs:
            return d.get("nota", NO_INFO_ANSWER)
        lines = ["Servicios recomendados del catálogo aprobado:"]
        for r in recs:
            prov = " | ".join(f"{k.upper()}: {r[k]}" for k in ("azure", "aws") if k in r)
            lines.append(f"- **{r['categoria']}** → {prov}. {r['caso_de_uso']}")
        return "\n".join(lines)
