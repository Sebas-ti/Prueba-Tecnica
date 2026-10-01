# Documentación de la API

La documentación interactiva (Swagger UI) está en `GET /docs` y el contrato OpenAPI en `GET /openapi.json` (copia versionada en [`openapi.json`](openapi.json)).

**Autenticación**: cabecera `X-API-Key`. Solo puede omitirse con `ENVIRONMENT=local|test` y `API_KEYS` vacío.
**Correlación**: envíe `X-Request-ID` (opcional); se devuelve en la respuesta y aparece en todos los logs.

## Endpoints

| Método | Ruta | Descripción |
| --- | --- | --- |
| POST | `/v1/chat` | Pregunta al asistente |
| POST | `/v1/documents` | Carga y procesa 1–20 archivos (`multipart/form-data`, campo `files`) |
| POST | `/v1/documents/reindex` | Re-indexa el corpus base de `data/docs` |
| GET | `/v1/documents` | Lista documentos indexados y número de chunks |
| DELETE | `/v1/documents/{source}` | Elimina un documento del índice |
| GET | `/v1/history` | Historial (`limit`, `session_id`, `status`) |
| GET | `/v1/history/{interaction_id}` | Detalle completo de una interacción |
| GET | `/v1/history/stats` | Conteo por estado |
| GET | `/v1/tools` | Herramientas del agente con su JSON Schema |
| GET | `/health` | Liveness |
| GET | `/ready` | Readiness: proveedores configurados y chunks indexados |

## POST /v1/chat

```http
POST /v1/chat
Content-Type: application/json
X-API-Key: <clave>

{ "question": "¿Cuál es el RTO de GESOL?", "session_id": "demo-session-01" }
```

- `question`: 2–2000 caracteres.
- `session_id` (opcional): `^[A-Za-z0-9_-]{6,64}$`. Reutilícelo para conversaciones multi-turno.

Respuesta `200`:

```json
{
  "interaction_id": "8f0c…",
  "session_id": "demo-session-01",
  "answer": "Según la documentación interna:\n- El objetivo de tiempo de recuperación (RTO) de GESOL es de 4 horas. [1]",
  "status": "answered",
  "sources": [
    {"ref": 1, "source": "procedimiento_continuidad_respaldo.md", "section": "1. Objetivos de recuperación",
     "page": null, "score": 0.4986, "snippet": "- El objetivo de tiempo de recuperación…", "cited": true}
  ],
  "tool_calls": [{"name": "buscar_documentacion", "arguments": {"query": "RTO de GESOL"}, "ok": true, "elapsed_ms": 1}],
  "grounding": {"score": 1.0, "grounded": true, "evaluated_sentences": 1, "unsupported_sentences": [], "invalid_citations": []},
  "security": {"injection_score": 0.0, "injection_matches": [], "blocked": false, "output_flags": []},
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 2},
  "model": "local-deterministic-v1",
  "prompt_version": "agent-v1.3",
  "latency_ms": 6
}
```

Valores de `status`:

| status | Significado |
| --- | --- |
| `answered` | Respuesta con fuentes y/o resultados de herramientas |
| `no_info` | No hay información suficiente en las fuentes (abstención) |
| `blocked` | Bloqueada por el guardrail de entrada (prompt injection) |
| `output_blocked` | La respuesta generada fue bloqueada por el guardrail de salida |
| `incomplete` | Se alcanzó el máximo de iteraciones del agente |

## POST /v1/documents

```bash
curl -X POST localhost:8000/v1/documents -H "X-API-Key: $KEY" \
  -F "files=@politica.pdf" -F "files=@procedimiento.docx"
```

Respuesta: `ingested[]` con `source`, `chunks`, `replaced_chunks` (versión anterior reemplazada), `flagged_chunks` (inyección neutralizada), `embedding_model`, `elapsed_ms`; `errors[]` para archivos rechazados; `total_chunks_in_index`.

Validaciones: extensión en `ALLOWED_EXTENSIONS`, tamaño ≤ `MAX_UPLOAD_MB`, firma mágica coherente (`%PDF`, `PK` para DOCX), nombre seguro (se usa solo el *basename*).

## Formato de errores

Todos los errores comparten el mismo formato:

```json
{ "error": { "code": "validation_error", "message": "Entrada inválida", "details": {…}, "request_id": "c30e6e…" } }
```

| HTTP | code |
| --- | --- |
| 400 | `bad_request` |
| 401 | `unauthorized` |
| 404 | `not_found` |
| 413 | `payload_too_large` |
| 415 | `unsupported_file` |
| 422 | `validation_error` |
| 429 | `rate_limited` |
| 500 | `internal_error` (sin detalles internos) |
| 502 | `upstream_error` (Azure OpenAI, AI Search o Cosmos) |

## Herramientas del agente

| Herramienta | Entrada | Salida |
| --- | --- | --- |
| `buscar_documentacion` | `query`, `top_k` | Fragmentos con `ref`, fuente, sección, relevancia y `cobertura_terminos` |
| `consultar_solicitud` | `request_id` (SOL-NNNN) | Datos públicos de la solicitud e historial (últimos 5) |
| `clasificar_prioridad` | `request_id` o `descripcion`, `impacto`, `urgencia`, `dias_para_fecha_limite` | P1–P4, SLA, justificación con reglas aplicadas |
| `calcular_esfuerzo` | `request_id` o `tipo`, `complejidad`, `sistemas_integrados`, `requiere_migracion_datos` | Horas, días-persona, talla y desglose |
| `resumen_ejecutivo` | `request_id` | Estado, prioridad, esfuerzo, última novedad y riesgos |
| `recomendar_servicios_cloud` | `necesidad`, `proveedor` (azure/aws/ambos) | Servicios del catálogo aprobado |

Evidencia de ejecución real de todos los endpoints: [`evidencias/api_smoke_test.md`](evidencias/api_smoke_test.md).
