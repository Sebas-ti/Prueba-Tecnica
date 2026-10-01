"""Orquestador del agente: bucle de razonamiento con herramientas + guardrails.

Flujo por pregunta:
  1. Guardrail de entrada (prompt injection directa) -> bloquea si riesgo alto.
  2. Construye mensajes: system prompt versionado + últimos turnos de la sesión.
  3. Bucle LLM <-> herramientas (máx. N iteraciones, llamadas en paralelo).
  4. Guardrail de salida (canario del system prompt, secretos).
  5. Verificación de fundamentación y validez de citas.
  6. Persistencia de la interacción completa (trazabilidad / auditoría).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

from app.agent.grounding import check_grounding
from app.agent.tools import ToolContext, ToolExecution, execute_tool, tool_schemas
from app.config import Settings
from app.core.logging import get_logger, redact
from app.core.security import assess_injection, output_leaks, sanitize_user_text
from app.llm.base import LLMClient
from app.llm.prompts import BLOCKED_ANSWER, LEAK_ANSWER, NO_INFO_ANSWER, PROMPT_VERSION, SYSTEM_PROMPT
from app.rag.knowledge_base import KnowledgeBase
from app.storage.history import HistoryStore
from app.storage.requests_repo import RequestRepository

log = get_logger(__name__)

MAX_TOOL_RESULT_CHARS = 12_000
HISTORY_TURNS = 3


@dataclass
class AgentResult:
    interaction_id: str
    session_id: str
    answer: str
    status: str  # answered | no_info | blocked | output_blocked | incomplete
    sources: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    grounding: dict | None = None
    security: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    model: str = ""
    prompt_version: str = PROMPT_VERSION
    latency_ms: int = 0


class Agent:
    def __init__(self, settings: Settings, llm: LLMClient, kb: KnowledgeBase, requests: RequestRepository,
                 cloud_catalog: list[dict], history: HistoryStore):
        self.settings = settings
        self.llm = llm
        self.kb = kb
        self.requests = requests
        self.cloud_catalog = cloud_catalog
        self.history = history

    def run(self, question: str, session_id: str | None = None, user_id: str = "anonymous") -> AgentResult:
        t0 = time.perf_counter()
        session_id = session_id or uuid.uuid4().hex
        interaction_id = uuid.uuid4().hex
        question = sanitize_user_text(question, self.settings.max_question_chars)
        assessment = assess_injection(question)
        security = {"injection_score": assessment.score, "injection_matches": assessment.matches,
                    "blocked": assessment.blocked, "output_flags": []}

        if assessment.blocked:
            log.warning("prompt_injection_blocked", extra={"matches": assessment.matches, "score": assessment.score})
            result = AgentResult(interaction_id=interaction_id, session_id=session_id, answer=BLOCKED_ANSWER,
                                 status="blocked", security=security, model=self.llm.model_name)
            return self._finish(result, question, user_id, t0)

        ctx = ToolContext(kb=self.kb, requests=self.requests, cloud_catalog=self.cloud_catalog)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, *self._session_messages(session_id),
                    {"role": "user", "content": question}]
        executions: list[ToolExecution] = []
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0}
        answer: str | None = None
        schemas = tool_schemas()

        for _ in range(self.settings.agent_max_iterations):
            resp = self.llm.chat(messages, schemas)
            usage["prompt_tokens"] += resp.prompt_tokens
            usage["completion_tokens"] += resp.completion_tokens
            usage["llm_calls"] += 1
            if not resp.tool_calls:
                answer = (resp.content or "").strip()
                break
            messages.append({
                "role": "assistant", "content": resp.content,
                "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.name, "arguments": c.arguments}}
                               for c in resp.tool_calls],
            })
            for call in resp.tool_calls:
                ex = execute_tool(ctx, call.name, call.arguments)
                executions.append(ex)
                payload = json.dumps(ex.result, ensure_ascii=False)[:MAX_TOOL_RESULT_CHARS]
                messages.append({"role": "tool", "tool_call_id": call.id, "content": payload})

        status = "answered"
        if answer is None:
            answer = "No pude completar la solicitud dentro del número máximo de pasos permitido. Intenta reformular la pregunta."
            status = "incomplete"
        elif not answer:
            answer, status = NO_INFO_ANSWER, "no_info"

        leaks = output_leaks(answer)
        if leaks:
            log.error("output_leak_blocked", extra={"flags": leaks})
            security["output_flags"] = leaks
            answer, status = LEAK_ANSWER, "output_blocked"

        if status == "answered" and NO_INFO_ANSWER[:60] in answer:
            successful_actions = [e for e in executions if e.ok and e.name != "buscar_documentacion"]
            status = "answered" if successful_actions else "no_info"

        sources = self._sources(answer, ctx) if status == "answered" else []
        grounding = None
        if status == "answered":
            contexts = [json.dumps(e.result, ensure_ascii=False) for e in executions]
            g = check_grounding(answer, contexts, len(ctx.citations))
            grounding = {"score": g.score, "grounded": g.grounded, "evaluated_sentences": g.evaluated_sentences,
                         "unsupported_sentences": g.unsupported, "invalid_citations": g.invalid_citations}
            if not g.grounded:
                log.warning("low_groundedness", extra={"score": g.score, "unsupported": len(g.unsupported)})

        result = AgentResult(
            interaction_id=interaction_id, session_id=session_id, answer=answer, status=status, sources=sources,
            tool_calls=[{"name": e.name, "arguments": e.arguments, "ok": e.ok, "elapsed_ms": e.elapsed_ms} for e in executions],
            grounding=grounding, security=security, usage=usage, model=self.llm.model_name,
        )
        return self._finish(result, question, user_id, t0)

    # ------------------------------------------------------------------
    def _session_messages(self, session_id: str) -> list[dict]:
        msgs: list[dict] = []
        for turn in self.history.session_turns(session_id, HISTORY_TURNS):
            if turn.get("status") in {"blocked", "output_blocked"}:
                continue  # no se reinyectan turnos maliciosos al contexto
            msgs.append({"role": "user", "content": turn["question"]})
            msgs.append({"role": "assistant", "content": turn["answer"]})
        return msgs

    @staticmethod
    def _sources(answer: str, ctx: ToolContext) -> list[dict]:
        import re

        cited = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
        out = []
        for ref, r in enumerate(ctx.citations, start=1):
            if cited and ref not in cited:
                continue
            snippet = r.text.split("\n", 1)[-1][:300]
            out.append({"ref": ref, "source": r.source, "section": r.section, "page": r.page,
                        "score": r.score, "snippet": snippet, "cited": ref in cited})
        return out

    def _finish(self, result: AgentResult, question: str, user_id: str, t0: float) -> AgentResult:
        result.latency_ms = int((time.perf_counter() - t0) * 1000)
        record = {
            "id": result.interaction_id,
            "session_id": result.session_id,
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "question": redact(question),
            **{k: v for k, v in asdict(result).items() if k not in {"interaction_id", "session_id"}},
        }
        record["answer"] = redact(record["answer"])
        try:
            self.history.save(record)
        except Exception:
            # La trazabilidad no debe tumbar la respuesta, pero sí alertar.
            log.exception("history_persist_failed")
        log.info("agent_interaction", extra={
            "interaction_id": result.interaction_id, "session_id": result.session_id, "status": result.status,
            "tools": [t["name"] for t in result.tool_calls], "sources": [s["source"] for s in result.sources],
            "groundedness": (result.grounding or {}).get("score"), "latency_ms": result.latency_ms,
            "model": result.model, "prompt_version": result.prompt_version, **result.usage,
        })
        return result
