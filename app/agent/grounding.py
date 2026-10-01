"""Verificación de fundamentación (groundedness) y validez de citas.

Heurística léxica rápida que corre en *cada* respuesta (costo ~0):
una oración se considera soportada si >= 60 % de sus términos de contenido
(incluidos números) aparecen en el contexto devuelto por las herramientas.
Detecta especialmente cifras o entidades inventadas.

Para evaluación offline más precisa se puede usar un LLM-juez (ver
eval/run_eval.py --judge) o Azure AI Foundry Evaluation (GroundednessEvaluator).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag.text import split_sentences, tokenize

_CITE = re.compile(r"\[(\d+)\]")
SUPPORT_THRESHOLD = 0.6


@dataclass
class GroundingResult:
    score: float
    evaluated_sentences: int
    unsupported: list[str] = field(default_factory=list)
    invalid_citations: list[int] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        return self.score >= 0.8 and not self.invalid_citations


def check_grounding(answer: str, contexts: list[str], n_citations: int) -> GroundingResult:
    ctx_tokens = set(tokenize(" ".join(contexts)))
    evaluated, unsupported = 0, []
    for raw in split_sentences(answer):
        sent = _CITE.sub("", raw).strip(" -*•\t")
        if len(sent) < 20 or sent.endswith(":"):
            continue
        toks = [t for t in tokenize(sent) if len(t) > 2 or t.isdigit()]
        if len(toks) < 3:
            continue
        evaluated += 1
        support = sum(t in ctx_tokens for t in toks) / len(toks)
        if support < SUPPORT_THRESHOLD:
            unsupported.append(sent[:200])
    cited = {int(n) for n in _CITE.findall(answer)}
    invalid = sorted(n for n in cited if n < 1 or n > n_citations)
    score = 1.0 if evaluated == 0 else round((evaluated - len(unsupported)) / evaluated, 3)
    return GroundingResult(score=score, evaluated_sentences=evaluated, unsupported=unsupported, invalid_citations=invalid)
