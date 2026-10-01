# CLAUDE.md — guía del proyecto para Claude Code

Agente RAG empresarial sobre Azure (prueba técnica AI Developer Engineer – IC7). Responder siempre en español.

## Comandos

- Instalar: `pip install -r requirements-dev.txt`
- Indexar corpus local: `python -m scripts.ingest`
- API local: `uvicorn app.main:app --reload --port 8000` (Swagger en /docs)
- Pruebas: `python -m pytest` · Lint: `ruff check .`
- Evaluación: `python -m eval.run_eval` · held-out: `python -m eval.run_eval --dataset eval/dataset_holdout.json --out eval/results/holdout`
- Evaluación contra Azure: `python -m eval.run_eval --api-url <URL> --api-key <KEY> [--judge]`
- Despliegue: `bash scripts/deploy_azure.sh <resource-group> [location]` (requiere `RAG_API_KEYS` y `az login`)

## Arquitectura (resumen)

- `app/api` rutas FastAPI · `app/agent` orquestador, herramientas (`tools.py`), reglas deterministas (`rules.py`), groundedness
- `app/rag` loaders, chunking, embeddings, vector stores (local numpy+BM25 / Azure AI Search) · `app/llm` Azure OpenAI y LLM local determinista
- `app/storage` historial (SQLite / Cosmos DB) y repositorio del legado · `app/core` logging JSON, guardrails, errores
- Proveedores por variables de entorno: `LLM_PROVIDER`, `VECTOR_STORE_PROVIDER`, `HISTORY_PROVIDER`
- IaC en `infra/` (Bicep). Documentación en `docs/`.

## Reglas

- Nunca escribir secretos en archivos versionados; `.env` está en `.gitignore`. No imprimir claves en la terminal.
- Después de cualquier cambio de código: ejecutar `ruff check .` y `python -m pytest`; si cambia el agente o el RAG, también la evaluación.
- Las reglas de negocio (prioridad, esfuerzo) deben quedar en `app/agent/rules.py` y coincidir con los documentos de `data/docs`.
- Antes de comandos `az` que creen o borren recursos, explicar qué harán y pedir confirmación.
- En Azure no hay claves locales (OpenAI, AI Search y Cosmos con `disableLocalAuth`): usar Entra ID / identidad administrada.
