# Guion del video (máx. 7 minutos)

Preparación: terminal con el repo, navegador en `http://localhost:8000/docs`, diagrama `docs/arquitectura.png` abierto, `eval/results/report.md` abierto. Si hay despliegue en Azure, tener a mano el portal (Container Apps, AI Search, App Insights).

| Tiempo | Bloque | Qué mostrar | Qué decir (idea clave) |
| --- | --- | --- | --- |
| 0:00–0:40 | Problema | Diapositiva o README | Los analistas pierden ~25 min por solicitud buscando en documentos y en GESOL. El asistente responde con fuentes, ejecuta acciones simples y deja traza auditable. |
| 0:40–1:50 | Arquitectura | `docs/arquitectura.png` | Una API FastAPI en Container Apps; agente con 6 herramientas; RAG híbrido en AI Search; Cosmos para trazabilidad; identidad administrada, sin claves. Puertos/adaptadores: el mismo código corre local o en Azure. |
| 1:50–2:30 | Ingesta | `POST /v1/documents/reindex` y subir `teletrabajo.md` en `/docs` | Chunking por secciones, tablas linealizadas, ingesta idempotente. Señalar `flagged_chunks: 1`: el anexo del proveedor traía una inyección y se neutralizó. |
| 2:30–3:40 | RAG + herramientas | `/v1/chat`: RTO/RPO (citas), resumen de SOL-1004, seguimiento "¿y qué prioridad le corresponde?" | Mostrar `sources`, `tool_calls`, `grounding`. Las reglas de prioridad y esfuerzo son código determinista alineado a los documentos, no el LLM "calculando". |
| 3:40–4:30 | Seguridad | Pregunta sin información (marketing 2027), inyección directa, SOL-1007 | Abstención en vez de alucinar; bloqueo antes del LLM; inyección indirecta en datos del legado no altera la prioridad. |
| 4:30–5:10 | Trazabilidad | `GET /v1/history?session_id=...`, log JSON con `request_id`, PII redactada | Cada respuesta es auditable: herramientas, argumentos, fuentes, versión de prompt, modelo, tokens, latencia. |
| 5:10–6:00 | Calidad | `make test` (63 pruebas) y `make eval` / reporte | 33 casos + 16 held-out; métricas de exactitud, recuperación, abstención, inyección. Explicar por qué el 100 % local es optimista y cómo se evalúa con LLM real y LLM-juez. |
| 6:00–6:40 | Azure y producción | `infra/main.bicep`, `scripts/deploy_azure.sh` (o portal) | Despliegue en 3 fases, Job de ingesta, CI con quality gate. Producción: red privada, APIM + Entra ID, security trimming, Prompt Shields, alertas de costo. |
| 6:40–7:00 | Cierre | README | Uso de IA en el desarrollo (defectos reales detectados por pruebas) y mejoras futuras. |

Comandos de apoyo para la demo:

```bash
make install && make ingest && make run          # terminal 1
curl -s -X POST localhost:8000/v1/chat -H 'Content-Type: application/json' \
  -d '{"question":"Dame un resumen ejecutivo de la SOL-1004","session_id":"demo-session-01"}' | jq
curl -s -X POST localhost:8000/v1/chat -H 'Content-Type: application/json' \
  -d '{"question":"¿Y qué prioridad le corresponde?","session_id":"demo-session-01"}' | jq .answer
curl -s 'localhost:8000/v1/history?session_id=demo-session-01' | jq '.items[] | {question, status, tools: [.tool_calls[].name]}'
```

Consejos: grabar a 1080p, aumentar el tamaño de fuente de la terminal, ensayar una vez con cronómetro y tener las respuestas pre-validadas (el modo local es determinista, así que la demo es reproducible).
