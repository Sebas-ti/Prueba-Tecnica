from app.rag.chunking import chunk_text, linearize_tables
from app.rag.embeddings import HashingEmbedder
from app.rag.text import split_sentences, tokenize

DOC = """# Manual X

## Sección A
Primer párrafo de la sección A. Tiene varias oraciones.

Segundo párrafo de la sección A.

## Sección B
### Subsección B1
Contenido de B1 sobre bases de datos Oracle.
"""


def test_chunks_respect_sections_and_carry_heading_path():
    chunks = chunk_text(DOC, source="x.md", chunk_size=200, chunk_overlap=20)
    sections = {c.section for c in chunks}
    assert "Sección A" in sections
    assert "Sección B > Subsección B1" in sections
    b1 = next(c for c in chunks if c.section.endswith("B1"))
    assert b1.text.startswith("[Manual X] Sección B > Subsección B1")
    assert "Oracle" in b1.text


def test_chunk_ids_are_deterministic():
    a = chunk_text(DOC, source="x.md", chunk_size=200, chunk_overlap=20)
    b = chunk_text(DOC, source="x.md", chunk_size=200, chunk_overlap=20)
    assert [c.id for c in a] == [c.id for c in b]


def test_long_text_is_split_within_size_with_overlap():
    text = "# T\n\n" + " ".join(f"Oración número {i} con algo de contenido." for i in range(200))
    chunks = chunk_text(text, source="t.md", chunk_size=400, chunk_overlap=80)
    assert len(chunks) > 5
    header_len = len("[T] ") + 1
    assert all(len(c.text) <= 400 + header_len for c in chunks)
    # El final de un chunk reaparece al inicio del siguiente (solape)
    tail = chunks[0].text.split("\n", 1)[1][-40:].split(" ", 1)[1]
    assert tail[:20] in chunks[1].text


def test_markdown_tables_are_linearized():
    table = "| Prioridad | Respuesta |\n| --- | --- |\n| P1 | 1 hora |\n| P2 | 4 horas |"
    out = linearize_tables(table)
    assert "Prioridad: P1; Respuesta: 1 hora." in out
    assert "---" not in out


def test_sentence_split_keeps_time_abbreviations():
    s = split_sentences("Corre a las 02:00 a. m. y dura 95 minutos. Luego termina.")
    assert s == ["Corre a las 02:00 a. m. y dura 95 minutos.", "Luego termina."]


def test_tokenizer_normalizes_accents_and_morphology():
    assert tokenize("Contraseñas")[0] == tokenize("contraseña")[0]
    assert tokenize("cambiarse") == tokenize("cambiar")


def test_hashing_embedder_similarity_is_meaningful():
    emb = HashingEmbedder()
    v = emb.embed(["respaldo de base de datos", "copia de seguridad de la base de datos", "receta de pastel"])
    assert v.shape == (3, emb.dimensions)
    assert float(v[0] @ v[1]) > float(v[0] @ v[2])
