"""Chunking consciente de estructura.

Estrategia:
1. Se divide el documento por encabezados Markdown para no mezclar secciones.
2. Cada sección se divide por párrafos y, si un párrafo excede el tamaño, por
   oraciones; se agrupan hasta `chunk_size` con `chunk_overlap` de solape.
3. Cada chunk lleva la ruta de encabezados ("Doc > Sección > Subsección") como
   prefijo: mejora la recuperación (contexto semántico) y la cita de fuentes.
4. El id del chunk es determinista (hash de fuente + posición + contenido), lo
   que hace la re-ingesta idempotente.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.rag.text import split_sentences

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)


@dataclass
class Chunk:
    id: str
    text: str
    source: str
    chunk_index: int
    section: str = ""
    page: int | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "text": self.text,
            "source": self.source,
            "chunk_index": self.chunk_index,
            "section": self.section,
            "page": self.page,
            "metadata": self.metadata,
        }


def linearize_tables(text: str) -> str:
    """Convierte tablas Markdown en oraciones "Columna: valor; ...".

    Cada fila queda autocontenida (con sus encabezados), de modo que un chunk o
    una oración recuperada conserva el significado aunque se separe de la tabla.
    """
    out, header = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue  # separador |---|
            if header is None:
                header = cells
                continue
            pairs = [f"{h}: {v}" for h, v in zip(header, cells, strict=False) if v]
            out.append("; ".join(pairs) + ".")
        else:
            header = None
            out.append(line)
    return "\n".join(out)


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Devuelve [(ruta_encabezados, cuerpo)]."""
    sections: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []
    last_end, last_path = 0, ""
    for m in _HEADING.finditer(text):
        body = text[last_end : m.start()].strip()
        if body:
            sections.append((last_path, body))
        level, title = len(m.group(1)), m.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        last_path = " > ".join(t for _, t in stack)
        last_end = m.end()
    tail = text[last_end:].strip()
    if tail:
        sections.append((last_path, tail))
    return sections or [("", text.strip())]


def _units(body: str, chunk_size: int) -> list[str]:
    units: list[str] = []
    for para in re.split(r"\n\s*\n", body):
        para = para.strip()
        if not para:
            continue
        if len(para) <= chunk_size:
            units.append(para)
        else:
            units.extend(split_sentences(para))
    # Oraciones aún demasiado largas: corte duro
    out = []
    for u in units:
        while len(u) > chunk_size:
            out.append(u[:chunk_size])
            u = u[chunk_size:]
        if u:
            out.append(u)
    return out


def _pack(units: list[str], chunk_size: int, overlap: int) -> list[str]:
    chunks, current = [], ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if len(candidate) <= chunk_size:
            current = candidate
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            # El solape empieza en un límite de palabra
            tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
            current = f"{tail}\n\n{unit}" if tail else unit
            if len(current) > chunk_size:
                current = unit
        else:
            current = unit
    if current:
        chunks.append(current)
    return chunks


def chunk_text(
    text: str,
    *,
    source: str,
    chunk_size: int,
    chunk_overlap: int,
    page: int | None = None,
    start_index: int = 0,
    doc_title: str | None = None,
) -> list[Chunk]:
    text = linearize_tables(text)
    h1 = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    title = h1.group(1).strip() if h1 else (doc_title or source)
    chunks: list[Chunk] = []
    idx = start_index
    for path, body in _split_sections(text):
        section = path.removeprefix(title).removeprefix(" > ") if path else ""
        for piece in _pack(_units(body, chunk_size), chunk_size, chunk_overlap):
            header = f"[{title}] {section}".strip()
            content = f"{header}\n{piece}"
            digest = hashlib.sha256(f"{source}|{idx}|{content}".encode()).hexdigest()[:32]
            chunks.append(Chunk(id=digest, text=content, source=source, chunk_index=idx,
                                section=section or title, page=page))
            idx += 1
    return chunks
