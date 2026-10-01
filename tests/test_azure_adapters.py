"""Prueba los adaptadores de Azure OpenAI con un cliente simulado (sin red).

Valida que el contrato del SDK (chat.completions con tools, embeddings) se
traduce correctamente al formato interno y que el agente completa el bucle
de herramientas con el adaptador real.
"""
import json
from types import SimpleNamespace as NS

import numpy as np

from app.agent.agent import Agent
from app.llm.azure_openai import AzureOpenAILLM
from app.rag.embeddings import AzureOpenAIEmbedder
from app.storage.history import SqliteHistoryStore
from tests.conftest import make_settings


class FakeCompletions:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        has_tool_result = any(m["role"] == "tool" for m in kwargs["messages"])
        if not has_tool_result:
            call = NS(id="call_1", function=NS(name="calcular_esfuerzo", arguments=json.dumps({"request_id": "SOL-1003"})))
            msg = NS(content=None, tool_calls=[call])
        else:
            result = json.loads(next(m for m in kwargs["messages"] if m["role"] == "tool")["content"])
            msg = NS(content=f"La SOL-1003 requiere {result['horas_estimadas']} horas (talla {result['talla']}).", tool_calls=None)
        return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=120, completion_tokens=30))


class FakeEmbeddings:
    def create(self, model, input, dimensions):
        rng = np.random.default_rng(len(input))
        return NS(data=[NS(embedding=rng.normal(size=dimensions).tolist()) for _ in input])


def fake_client():
    return NS(chat=NS(completions=FakeCompletions()), embeddings=FakeEmbeddings())


def test_azure_llm_adapter_with_tool_loop(tmp_path, indexed_container):
    settings = make_settings(tmp_path, llm_provider="azure", azure_openai_endpoint="https://fake.openai.azure.com")
    client = fake_client()
    llm = AzureOpenAILLM(settings, client=client)
    agent = Agent(settings, llm, indexed_container.kb, indexed_container.agent.requests, [],
                  SqliteHistoryStore(str(tmp_path / "h.db")))
    r = agent.run("¿Cuánto esfuerzo requiere la SOL-1003?")
    assert r.status == "answered"
    assert "122 horas" in r.answer
    assert r.usage == {"prompt_tokens": 240, "completion_tokens": 60, "llm_calls": 2}
    first = client.chat.completions.requests[0]
    assert first["tool_choice"] == "auto" and len(first["tools"]) >= 2
    # gpt-5-mini (por defecto) es de razonamiento: sin temperature ni max_tokens
    assert "temperature" not in first and "max_tokens" not in first
    assert first["reasoning_effort"] == "low" and first["max_completion_tokens"] > 0
    assert first["messages"][0]["role"] == "system"
    assert r.grounding["grounded"]


def test_classic_model_uses_temperature_and_max_tokens(tmp_path):
    settings = make_settings(tmp_path, llm_provider="azure", azure_openai_endpoint="https://fake.openai.azure.com",
                             azure_openai_chat_deployment="gpt-4.1-mini")
    client = fake_client()
    AzureOpenAILLM(settings, client=client).chat([{"role": "user", "content": "hola"}])
    req = client.chat.completions.requests[0]
    assert req["temperature"] == 0.0 and req["max_tokens"] == settings.llm_max_tokens
    assert "reasoning_effort" not in req


def test_azure_embedder_normalizes_and_batches(tmp_path):
    settings = make_settings(tmp_path, llm_provider="azure", azure_openai_endpoint="https://fake.openai.azure.com",
                             embedding_dimensions=64)
    emb = AzureOpenAIEmbedder(settings, client=fake_client())
    vecs = emb.embed([f"texto {i}" for i in range(40)])
    assert vecs.shape == (40, 64)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-5)
