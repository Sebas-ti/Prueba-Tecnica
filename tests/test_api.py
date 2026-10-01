from pathlib import Path

from fastapi.testclient import TestClient

from app.container import Container
from app.main import create_app
from tests.conftest import make_settings


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    ready = client.get("/ready").json()
    assert ready["indexed_chunks"] > 0
    assert ready["llm"] == "local-deterministic-v1"


def test_chat_returns_answer_sources_and_trace(client):
    r = client.post("/v1/chat", json={"question": "¿Cuál es el RTO de GESOL?"})
    assert r.status_code == 200
    body = r.json()
    assert "4 horas" in body["answer"]
    assert body["sources"][0]["source"].startswith("procedimiento_continuidad")
    assert body["tool_calls"][0]["name"] == "buscar_documentacion"
    assert r.headers["X-Request-ID"]


def test_chat_input_validation(client):
    assert client.post("/v1/chat", json={"question": ""}).status_code == 422
    assert client.post("/v1/chat", json={"question": "x" * 2001}).status_code == 422
    assert client.post("/v1/chat", json={"question": "hola", "session_id": "../../etc"}).status_code == 422
    err = client.post("/v1/chat", json={}).json()
    assert err["error"]["code"] == "validation_error" and err["error"]["request_id"]


def test_upload_and_query_new_document(client):
    content = "# Política de Teletrabajo\n\nLos colaboradores pueden teletrabajar máximo 3 días por semana.".encode()
    r = client.post("/v1/documents", files=[("files", ("teletrabajo.md", content, "text/markdown"))])
    assert r.status_code == 200, r.text
    assert r.json()["ingested"][0]["chunks"] >= 1
    assert any(d["source"] == "teletrabajo.md" for d in client.get("/v1/documents").json())
    ans = client.post("/v1/chat", json={"question": "¿Cuántos días por semana se puede teletrabajar?"}).json()
    assert "3 días" in ans["answer"]
    assert client.delete("/v1/documents/teletrabajo.md").json()["removed_chunks"] >= 1


def test_upload_rejects_bad_files(client):
    bad_ext = client.post("/v1/documents", files=[("files", ("malware.exe", b"MZ...", "application/octet-stream"))])
    assert bad_ext.status_code == 400 and bad_ext.json()["error"]["details"]["errors"][0]["code"] == "unsupported_file"
    fake_pdf = client.post("/v1/documents", files=[("files", ("doc.pdf", b"not a pdf", "application/pdf"))])
    assert fake_pdf.status_code == 400
    traversal = client.post("/v1/documents", files=[("files", ("../../x.md", b"hola", "text/markdown"))])
    # El nombre se reduce al basename: nunca se escribe fuera del índice
    assert traversal.status_code == 200 and traversal.json()["ingested"][0]["source"] == "x.md"


def test_history_endpoints(client):
    r = client.post("/v1/chat", json={"question": "¿Cuál es el estado de la SOL-1004?"}).json()
    hist = client.get("/v1/history", params={"limit": 5}).json()
    assert hist["count"] >= 1
    detail = client.get(f"/v1/history/{r['interaction_id']}").json()
    assert detail["tool_calls"][0]["name"] == "consultar_solicitud"
    assert client.get("/v1/history/stats").json()["total"] >= 1
    assert client.get("/v1/history/noexiste").status_code == 404


def test_feedback_endpoint(client):
    r = client.post("/v1/chat", json={"question": "¿Cuál es el estado de la SOL-1004?"}).json()
    fb = client.post("/v1/feedback", json={"interaction_id": r["interaction_id"], "rating": "up"})
    assert fb.status_code == 200, fb.text
    assert fb.json()["feedback"]["rating"] == "up"
    detail = client.get(f"/v1/history/{r['interaction_id']}").json()
    assert detail["feedback"]["rating"] == "up"
    assert client.post("/v1/feedback", json={"interaction_id": "noexiste", "rating": "up"}).status_code == 404
    assert client.post("/v1/feedback", json={"interaction_id": r["interaction_id"], "rating": "maybe"}).status_code == 422


def test_console_is_served(client):
    r = client.get("/console")
    assert r.status_code == 200
    assert "Consola GESOL" in r.text


def test_api_key_required_when_configured(tmp_path):
    s = make_settings(tmp_path, api_keys="clave-secreta-1,clave-2")
    with TestClient(create_app(s, Container.build(s))) as c:
        assert c.post("/v1/chat", json={"question": "hola"}).status_code == 401
        assert c.post("/v1/chat", json={"question": "hola"}, headers={"X-API-Key": "mala"}).status_code == 401
        assert c.get("/v1/history", headers={"X-API-Key": "clave-2"}).status_code == 200


def test_rate_limit(tmp_path):
    s = make_settings(tmp_path, api_keys="rl-key", rate_limit_per_minute=3)
    with TestClient(create_app(s, Container.build(s))) as c:
        codes = [c.post("/v1/chat", json={"question": "hola"}, headers={"X-API-Key": "rl-key"}).status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and codes[-1] == 429


def test_openapi_documents_all_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ["/v1/chat", "/v1/documents", "/v1/history", "/v1/history/{interaction_id}", "/health"]:
        assert p in paths


def test_sample_binary_documents_are_indexed(client):
    sources = {d["source"] for d in client.get("/v1/documents").json()}
    assert {"faq_mesa_servicios.docx", "acta_comite_arquitectura_2026_09.pdf"} <= sources
    assert Path("data/docs/faq_mesa_servicios.docx").exists()
