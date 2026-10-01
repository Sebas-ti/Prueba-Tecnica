# Evidencia: operación y trazabilidad en Application Insights

Capturado el 2026-10-01 contra el recurso `appi-ic7rag-dev-rumi5` (App Insights) con
`az monitor app-insights query`, sin necesidad de abrir el portal.

## 1. Latencia agregada por estado (tráfico real de esta sesión)

```kusto
traces
| where message == 'agent_interaction'
| extend status = tostring(customDimensions.status), latency = todouble(customDimensions.latency_ms)
| summarize n=count(), p50=percentile(latency,50), p95=percentile(latency,95) by status
| order by n desc
```

| status | n | p50 (ms) | p95 (ms) |
| --- | --- | --- | --- |
| answered | 186 | 5 070 | 13 269 |
| no_info | 23 | 6 880 | 11 360 |
| blocked | 14 | 0 | 0 |

`blocked` tiene latencia ~0 ms porque el guardrail de inyección actúa **antes** de llamar al LLM — confirma en producción lo que se afirma en la documentación de seguridad.

## 2. Correlación de extremo a extremo (`operation_Id`)

El `request_id` propio de los logs JSON locales no se exporta como campo indexado a Application Insights (limitación encontrada al intentar correlacionar por ese campo); la correlación real en Azure se logra con el `operation_Id` nativo de App Insights, que agrupa automáticamente todo lo emitido durante una misma petición:

```kusto
traces | where operation_Id == 'a4024b9d75c9a5c590413a887b030a9c' | project timestamp, message, customDimensions | order by timestamp asc
```

| timestamp | message | detalle |
| --- | --- | --- |
| 21:51:29.525 | `tool_executed` | `consultar_solicitud` sobre `SOL-1006`, 0 ms |
| 21:51:36.190 | `agent_interaction` | `interaction_id=cdfbdd2e13…`, `status=answered`, `latency_ms=8123`, `model=gpt-5-mini`, `prompt_version=agent-v1.4` |
| 21:51:36.192 | `http_request` | `POST /v1/chat` → `200`, `elapsed_ms=8134` |

Los tres eventos de una misma petición HTTP quedan agrupados bajo un único `operation_Id`, y el `interaction_id` permite cruzar esta traza con el documento correspondiente en Cosmos DB (mismo id).

## 3. Prueba de carga corta (20 peticiones reales, concurrencia 5)

```bash
seq 1 20 | xargs -P 5 -I{} curl ... -X POST $API/v1/chat -d '{"question":"¿Cuál es el RTO de GESOL?"}'
```

| Código | Cantidad |
| --- | --- |
| 200 | 13 |
| 502 (`upstream_error` / `rate_limit_exceeded` de Azure OpenAI) | 7 |

Para las 13 exitosas: **p50 ≈ 4,9 s, p95 ≈ 12,1 s** (min 3,6 s, max 12,1 s).

**Hallazgo consistente con la prueba de seguridad (sección 2 de `seguridad.md`)**: incluso con concurrencia moderada (5, no 20-25) y todas las peticiones repitiendo la misma pregunta, la capacidad `GlobalStandard=30` del deployment `gpt-5-mini` ya produce throttling real (35 % de las peticiones en 502). **Recomendación de producción**: antes de exponer el sistema a más de un puñado de usuarios concurrentes, aumentar la capacidad TPM del deployment y/o agregar reintento con backoff exponencial en el cliente (o en una capa de API Management delante).

## Resumen para el video

- Logging estructurado real en Application Insights, consultable por KQL sin portal.
- Trazabilidad de extremo a extremo confirmada por `operation_Id` → `interaction_id` → documento en Cosmos.
- Latencia real medida, no estimada: ~5 s p50 en preguntas respondidas.
- Límite de capacidad real identificado y cuantificado, con recomendación concreta — no una advertencia genérica de "hay que monitorear esto".
