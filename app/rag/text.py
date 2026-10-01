"""Normalización léxica en español para el modo local (embeddings por hashing y BM25)."""
from __future__ import annotations

import re
import unicodedata

_STOPWORDS = set(
    """a al algo algun alguna algunas alguno algunos ante antes asi aun bajo cada como con contra cual cuales
    cuando de del desde donde dos e el ella ellas ello ellos en entre era eran es esa esas ese eso esos esta
    estan estas este esto estos fue fueron ha han hasta hay la las le les lo los mas me mi mis mucho muy nada
    ni no nos o otra otras otro otros para pero poco por porque que quien quienes se sea segun ser si sin
    sobre su sus tambien tan te tiene tienen todo todos tu tus u un una unas uno unos y ya yo cual cuanto
    cuanta cuantos cuantas debe deben puede pueden hace hacer the of and to in is are what which how""".split()
)

_TOKEN = re.compile(r"[a-z0-9]+")
# Fin de oración, sin cortar abreviaturas de una letra ("a. m.", "S. A.").
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\b\w\.)\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s and s.strip()]


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


_SUFFIXES = (
    "aciones", "iciones", "amiento", "imiento", "acion", "icion", "cion", "mente", "ancia", "encia",
    "ables", "ibles", "istas", "able", "ible", "ista", "arse", "erse", "irse", "ando", "iendo",
    "ado", "ido", "ada", "ida", "dor", "dora", "ar", "er", "ir", "an", "en", "a", "o", "e",
)


def stem(token: str) -> str:
    """Stemmer ligero para español: plural + un sufijo derivativo/verbal.

    No es Snowball, pero es determinista y suficiente para el modo local
    (cambiar/cambiarse/cambian -> "cambi"; duración/dura -> "dura").
    """
    if token.isdigit() or len(token) <= 4 or any(ch.isdigit() for ch in token):
        return token
    if token.endswith("es") and len(token) > 6:
        token = token[:-2]
    elif token.endswith("s"):
        token = token[:-1]
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    text = strip_accents(text.lower())
    return [stem(t) for t in _TOKEN.findall(text) if t not in _STOPWORDS]
