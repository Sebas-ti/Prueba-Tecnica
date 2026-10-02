"""Guardrails de seguridad para LLM.

Defensa en capas contra prompt injection y fuga de datos:

1. **Entrada (directa)**: heurísticas que detectan intentos de sobrescribir
   instrucciones, extraer el system prompt o cambiar de rol. Si el riesgo es
   alto se bloquea antes de llamar al modelo (ahorra costo y reduce superficie).
2. **Contexto (indirecta)**: los fragmentos recuperados son *datos*, no
   instrucciones. Se marcan con delimitadores ("spotlighting") y se neutralizan
   líneas con patrones de instrucción embebidos en documentos.
3. **Salida**: se verifica que la respuesta no contenga el canario del system
   prompt ni secretos/PII, y se valida la fundamentación (grounding.py).

Las heurísticas no reemplazan a Azure AI Content Safety (Prompt Shields), que
es la recomendación para producción; se documentan como capa complementaria.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass, field

# Canario: token aleatorio por proceso insertado en el system prompt. Si
# aparece en una respuesta, el modelo filtró sus instrucciones.
SYSTEM_PROMPT_CANARY = f"CANARY-{secrets.token_hex(6)}"

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str], float]] = [
    ("override_es", re.compile(r"\b(ignor[ae]|olvid[ae]|omit[ae]|descart[ae])\w*\b.{0,40}\b(instrucciones|reglas|indicaciones|anterior(es)?|prompt)\b"), 0.9),
    ("override_en", re.compile(r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions|rules|previous|above|prompt)\b"), 0.9),
    ("reveal_prompt", re.compile(r"\b(muestr|muestra|revel|imprim|repit|dime|show|reveal|print|repeat)\w*\b.{0,40}\b(system prompt|prompt del sistema|instrucciones (del sistema|internas|iniciales)|your instructions|tus instrucciones)\b"), 0.9),
    ("role_switch", re.compile(r"\b(ahora eres|act[uú]a como|you are now|pretend to be|from now on you)\b"), 0.6),
    ("jailbreak", re.compile(r"\b(dan mode|developer mode|modo desarrollador|sin restricciones|without restrictions|jailbreak)\b"), 0.8),
    ("fake_system", re.compile(r"(^|\n)\s*(system|sistema|assistant)\s*:", re.IGNORECASE), 0.6),
    ("secrets", re.compile(r"\b(api[ _-]?key|contraseñ?a|password|connection string|cadena de conexi[oó]n|secret)s?\b.{0,30}\b(dame|muestra|revela|give|show|print)\b|\b(dame|muestra|revela|give|show|print)\b.{0,30}\b(api[ _-]?key|contraseñ?a|password|connection string|cadena de conexi[oó]n|secret)"), 0.8),
    ("exfiltration", re.compile(r"!\[[^\]]*\]\(https?://|\b(env[ií]a|send|post)\b.{0,40}\bhttps?://"), 0.7),
]

BLOCK_THRESHOLD = 0.8


@dataclass
class InjectionAssessment:
    score: float
    matches: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.score >= BLOCK_THRESHOLD


def _normalize(text: str) -> str:
    # Quita tildes/variantes unicode y caracteres de ancho cero que se usan
    # para evadir filtros ("i​gnora").
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[​-‏⁠﻿]", "", text)
    return text.lower()


def assess_injection(text: str) -> InjectionAssessment:
    norm = _normalize(text)
    stripped = "".join(c for c in unicodedata.normalize("NFD", norm) if unicodedata.category(c) != "Mn")
    score, matches = 0.0, []
    for name, pattern, weight in _INJECTION_PATTERNS:
        if pattern.search(norm) or pattern.search(stripped):
            matches.append(name)
            score = max(score, weight)
    if len(matches) >= 2:
        score = min(1.0, score + 0.1)
    return InjectionAssessment(score=score, matches=matches)


def neutralize_context(text: str) -> tuple[str, bool]:
    """Neutraliza instrucciones embebidas en documentos (inyección indirecta).

    Devuelve el texto con las oraciones sospechosas eliminadas (en silencio, sin
    dejar ningún marcador en el texto que recibe el modelo: un LLM real puede
    repetirle ese marcador al usuario, lo cual filtra un detalle de implementación
    interno) y un flag para auditoría — el flag, no el texto, es lo que se registra
    y cuenta en `flagged_chunks`.
    """
    flagged = False
    out_lines = []
    for line in text.splitlines():
        if assess_injection(line).score < 0.6:
            out_lines.append(line)
            continue
        flagged = True
        # Se remueve solo la oración sospechosa, conservando el resto de la línea.
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = [s for s in sentences if assess_injection(s).score < 0.6]
        if kept:
            out_lines.append(" ".join(kept))
        # Si la línea entera era maliciosa, se omite sin dejar rastro en el texto.
    return "\n".join(out_lines), flagged


def sanitize_user_text(text: str, max_chars: int) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)  # caracteres de control
    text = re.sub(r"[​-‏⁠﻿]", "", text)
    return text.strip()[:max_chars]


_OUTPUT_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"(?i)AccountKey=[A-Za-z0-9+/=]{20,}"),
    re.compile(r"(?i)InstrumentationKey=[0-9a-f-]{36}"),
]


def output_leaks(text: str) -> list[str]:
    issues = []
    if SYSTEM_PROMPT_CANARY in text:
        issues.append("system_prompt_canary")
    for p in _OUTPUT_SECRET_PATTERNS:
        if p.search(text):
            issues.append("secret_pattern")
    return issues
